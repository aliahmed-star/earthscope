"""One-day-ahead Cairo T2M statistical model (standardized ridge regression).

This module deliberately uses only NumPy and the Python standard library. It
is not an operational weather forecast. Rows are formed by exact calendar-date
lookups: every model input is known no later than the day before its target.
"""
from __future__ import annotations

import importlib
import inspect
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np

MODEL_ALGORITHM_VERSION = "standardized-ridge-v1"
MODEL_VERSION_PREFIX = "cairo-t2m-next-day"
LOCATION_ID = "cairo-eg"
VARIABLE = "T2M"
DEFAULT_UNITS = "°C"
DISCLAIMER = (
    "Statistical model estimate, not an operational weather forecast. "
    "Performance is historical and is not a guarantee of future accuracy."
)

FEATURE_NAMES = (
    "target_doy_sin",
    "target_doy_cos",
    "lag_1",
    "lag_2",
    "lag_7",
    "lag_14",
    "lag_30",
    "lag_365",
    "rolling_mean_7",
    "rolling_mean_30",
)

DEFAULT_SPLIT_PERIODS = {
    "train": ("1981-01-01", "2019-12-31"),
    "validation": ("2020-01-01", "2022-12-31"),
    "test": ("2023-01-01", "2025-12-31"),
}
DEFAULT_ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0)


class InsufficientDataError(ValueError):
    """Raised when history cannot form the requested training/prediction rows."""


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return date.fromisoformat(text[:10])
        except ValueError as exc:
            raise ValueError(f"Invalid ISO date: {value!r}") from exc
    raise TypeError(f"Expected date or ISO date string, got {type(value).__name__}")


def _normalise_series(series: Any) -> dict[date, float | None]:
    """Convert store records, (date, value) pairs, or date->value mappings.

    Duplicate dates are rejected rather than silently choosing one; missing,
    boolean, malformed, and non-finite measurements are retained as missing.
    """
    if isinstance(series, Mapping):
        items = series.items()
    else:
        try:
            items = []
            for item in series:
                if isinstance(item, Mapping):
                    items.append((item.get("date"), item.get("value")))
                else:
                    date_value, measurement = item
                    items.append((date_value, measurement))
        except (TypeError, ValueError) as exc:
            raise TypeError("Series must be a date/value mapping or iterable of records") from exc

    values: dict[date, float | None] = {}
    for raw_day, raw_value in items:
        day = _as_date(raw_day)
        if day in values:
            raise ValueError(f"Duplicate observation for {day.isoformat()}")
        parsed: float | None
        try:
            if raw_value is None or isinstance(raw_value, bool):
                parsed = None
            else:
                number = float(raw_value)
                parsed = number if math.isfinite(number) else None
        except (TypeError, ValueError, OverflowError):
            parsed = None
        values[day] = parsed
    return values


def _target_year_previous_day(target_day: date) -> date:
    """Same month/day in the prior year, mapping Feb 29 to Feb 28."""
    try:
        return target_day.replace(year=target_day.year - 1)
    except ValueError:  # Feb. 29 in a leap year
        return target_day.replace(year=target_day.year - 1, day=28)


def _features_for_target(values: Mapping[date, float | None], target_day: date) -> dict[str, float] | None:
    """Build features only from dates strictly before target_day."""
    def observed(day: date) -> float | None:
        value = values.get(day)
        return value if value is not None and math.isfinite(value) else None

    prior = target_day - timedelta(days=1)
    offsets = (1, 2, 7, 14, 30, 365)
    lag_values: dict[int, float] = {}
    for offset in offsets:
        value = observed(target_day - timedelta(days=offset))
        if value is None:
            return None
        lag_values[offset] = value

    rolling: dict[int, float] = {}
    for window in (7, 30):
        window_values = [
            observed(target_day - timedelta(days=offset))
            for offset in range(1, window + 1)
        ]
        if any(value is None for value in window_values):
            return None
        rolling[window] = float(sum(window_values) / window)

    # The seasonal-naive baseline is required on the same rows as the model.
    # This also guarantees comparable sample counts for all three test methods.
    seasonal_value = observed(_target_year_previous_day(target_day))
    if seasonal_value is None:
        return None

    # prior is assigned explicitly above to make the one-day-ahead origin clear.
    # The feature set only uses exact dates before target_day.
    day_angle = 2.0 * math.pi * (target_day.timetuple().tm_yday - 1) / 365.2425
    features = {
        "target_doy_sin": math.sin(day_angle),
        "target_doy_cos": math.cos(day_angle),
        "lag_1": lag_values[1],
        "lag_2": lag_values[2],
        "lag_7": lag_values[7],
        "lag_14": lag_values[14],
        "lag_30": lag_values[30],
        "lag_365": lag_values[365],
        "rolling_mean_7": rolling[7],
        "rolling_mean_30": rolling[30],
    }
    # Accessing prior also documents/guards that the immediate previous day is
    # part of the required inputs (it is the lag_1 feature).
    assert prior == target_day - timedelta(days=1)
    return features


def build_training_rows(series: Any) -> list[dict[str, Any]]:
    """Build complete daily supervised rows from archived ``date,value`` data.

    A row's target is T2M on ``target_date``. Features are target-date annual
    sine/cosine plus exact historical lags and means over the prior 7/30 days.
    Any missing required feature, target, or seasonal-naive baseline drops that
    row; no gaps are imputed and no target/future value enters its features.
    """
    values = _normalise_series(series)
    rows: list[dict[str, Any]] = []
    for target_day in sorted(values):
        target = values[target_day]
        if target is None:
            continue
        features = _features_for_target(values, target_day)
        if features is None:
            continue
        seasonal_day = _target_year_previous_day(target_day)
        seasonal_value = values.get(seasonal_day)
        persistence_value = values.get(target_day - timedelta(days=1))
        if seasonal_value is None or persistence_value is None:
            continue
        rows.append({
            "target_date": target_day.isoformat(),
            "target": float(target),
            "features": features,
            "baselines": {
                "persistence": float(persistence_value),
                "seasonal_naive": float(seasonal_value),
            },
        })
    return rows


def chronological_split(
    rows: list[dict[str, Any]],
    periods: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Partition rows by exact inclusive date ranges in chronological order.

    ``periods`` may override the default train/validation/test periods, e.g.
    ``{"train": ("2000-01-01", "2000-01-31"), ...}``, allowing tests and
    smaller custom datasets to use exact time splits. Rows outside ranges are
    omitted; overlapping ranges and empty partitions are clear errors.
    """
    ranges = dict(periods or DEFAULT_SPLIT_PERIODS)
    if set(ranges) != {"train", "validation", "test"}:
        raise ValueError("periods must define exactly train, validation, and test")
    normalised: dict[str, tuple[date, date]] = {}
    for name in ("train", "validation", "test"):
        bounds = ranges[name]
        if len(bounds) != 2:
            raise ValueError(f"{name} period must have inclusive start and end dates")
        start, end = map(_as_date, bounds)
        if end < start:
            raise ValueError(f"{name} period ends before it starts")
        normalised[name] = (start, end)
    if not (normalised["train"][1] < normalised["validation"][0]
            and normalised["validation"][1] < normalised["test"][0]):
        raise ValueError("train, validation, and test date ranges must be strictly chronological and non-overlapping")

    result = {name: [] for name in ("train", "validation", "test")}
    for row in sorted(rows, key=lambda item: _as_date(item["target_date"])):
        day = _as_date(row["target_date"])
        for name, (start, end) in normalised.items():
            if start <= day <= end:
                result[name].append(row)
                break
    empty = [name for name, partition in result.items() if not partition]
    if empty:
        raise InsufficientDataError(
            "Insufficient rows for chronological split: empty " + ", ".join(empty)
            + ". Check the input history or provide custom exact split periods."
        )
    return result


def calculate_metrics(
    actual: Any,
    predicted: Any,
    dates: Any = None,
    units: str = DEFAULT_UNITS,
) -> dict[str, Any]:
    """Return MAE, RMSE, prediction-minus-observation bias, R² and coverage."""
    observed = np.asarray(actual, dtype=float).reshape(-1)
    estimates = np.asarray(predicted, dtype=float).reshape(-1)
    if observed.size != estimates.size:
        raise ValueError("actual and predicted arrays must have equal length")
    if observed.size == 0:
        raise InsufficientDataError("Cannot calculate metrics with zero samples")
    if not np.isfinite(observed).all() or not np.isfinite(estimates).all():
        raise ValueError("actual and predicted values must all be finite")
    residual = estimates - observed
    sse = float(np.dot(residual, residual))
    centered = observed - float(np.mean(observed))
    sst = float(np.dot(centered, centered))
    r2 = None if observed.size < 2 or sst == 0.0 else float(1.0 - sse / sst)
    period = None
    if dates is not None:
        date_values = [_as_date(value) for value in dates]
        if len(date_values) != observed.size:
            raise ValueError("dates length must match actual and predicted arrays")
        period = {"start": min(date_values).isoformat(), "end": max(date_values).isoformat()}
    return {
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(residual * residual))),
        "bias": float(np.mean(residual)),
        "r2": r2,
        "sample_count": int(observed.size),
        "period": period,
        "units": str(units),
    }


def _feature_matrix(rows: list[dict[str, Any]]) -> np.ndarray:
    try:
        matrix = np.asarray(
            [[float(row["features"][name]) for name in FEATURE_NAMES] for row in rows],
            dtype=float,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Rows do not contain the required finite feature set") from exc
    if matrix.ndim != 2 or matrix.shape[1] != len(FEATURE_NAMES) or not np.isfinite(matrix).all():
        raise ValueError("Feature matrix contains missing or non-finite values")
    return matrix


def _fit_ridge(rows: list[dict[str, Any]], alpha: float, units: str, model_version: str) -> dict[str, Any]:
    if not rows:
        raise InsufficientDataError("Cannot train ridge regression with zero rows")
    x = _feature_matrix(rows)
    y = np.asarray([float(row["target"]) for row in rows], dtype=float)
    if not np.isfinite(y).all():
        raise ValueError("Training targets must be finite")
    mean = np.mean(x, axis=0)
    std = np.std(x, axis=0, ddof=0)
    std = np.where(std > 0.0, std, 1.0)
    z = (x - mean) / std
    y_mean = float(np.mean(y))
    centered_y = y - y_mean
    gram = z.T @ z + float(alpha) * np.eye(z.shape[1], dtype=float)
    coefficients = np.linalg.solve(gram, z.T @ centered_y)
    # Store the intercept in standardized coordinates: y_mean + z @ beta.
    return {
        "model_version": model_version,
        "algorithm_version": MODEL_ALGORITHM_VERSION,
        "model_type": "standardized_ridge_regression",
        "feature_names": list(FEATURE_NAMES),
        "feature_mean": mean.astype(float).tolist(),
        "feature_std": std.astype(float).tolist(),
        "coefficients": coefficients.astype(float).tolist(),
        "intercept": float(y_mean),
        "alpha": float(alpha),
        "units": units,
        "scaler_convention": "prediction = intercept + sum(((feature-mean)/std)*coefficient)",
    }


def predict_from_features(features: Mapping[str, Any], model: Mapping[str, Any]) -> float:
    names = model.get("feature_names")
    if names != list(FEATURE_NAMES):
        raise ValueError("Model feature names or order are incompatible")
    vector = np.asarray([float(features[name]) for name in names], dtype=float)
    mean = np.asarray(model["feature_mean"], dtype=float)
    std = np.asarray(model["feature_std"], dtype=float)
    coef = np.asarray(model["coefficients"], dtype=float)
    if any(arr.shape != vector.shape for arr in (mean, std, coef)):
        raise ValueError("Model scaler/coefficients have inconsistent dimensions")
    if not all(np.isfinite(arr).all() for arr in (vector, mean, std, coef)) or np.any(std <= 0):
        raise ValueError("Model and feature values must be finite with positive feature scales")
    result = float(model["intercept"] + np.dot((vector - mean) / std, coef))
    if not math.isfinite(result):
        raise ValueError("Model produced a non-finite estimate")
    return result


def _period_summary(rows: list[dict[str, Any]]) -> dict[str, str]:
    dates = [_as_date(row["target_date"]) for row in rows]
    return {"start": min(dates).isoformat(), "end": max(dates).isoformat()}


def _metric_for_rows(rows: list[dict[str, Any]], predictions: list[float], units: str) -> dict[str, Any]:
    return calculate_metrics(
        [row["target"] for row in rows], predictions,
        [row["target_date"] for row in rows], units,
    )


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def train_temperature_model(
    series: Any,
    *,
    alpha_candidates: Any = DEFAULT_ALPHAS,
    split_periods: Mapping[str, tuple[str, str]] | None = None,
    units: str = DEFAULT_UNITS,
    sources: list[str] | None = None,
    model_version: str | None = None,
    train_timestamp: str | None = None,
    history_store: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Tune alpha on validation MAE, then evaluate once on held-out test rows.

    The fitted model is trained only on the training period. Test observations
    are not involved in scaling, coefficient fitting, or alpha selection.
    Returns ``(model_artifact, metadata)``. An optional store instance/path is
    used for persistence if a compatible HistoryStore is installed.
    """
    rows = build_training_rows(series)
    partitions = chronological_split(rows, split_periods)
    train_rows = partitions["train"]
    validation_rows = partitions["validation"]
    test_rows = partitions["test"]
    try:
        candidates = [float(alpha) for alpha in alpha_candidates]
    except (TypeError, ValueError) as exc:
        raise ValueError("alpha_candidates must be a non-empty iterable of positive numbers") from exc
    if not candidates or any(not math.isfinite(alpha) or alpha <= 0.0 for alpha in candidates):
        raise ValueError("alpha_candidates must contain only finite positive values")

    timestamp = train_timestamp or _timestamp_now()
    version = model_version or f"{MODEL_VERSION_PREFIX}-{timestamp.replace(':', '').replace('-', '')}"
    val_results: list[dict[str, Any]] = []
    best: tuple[float, int, dict[str, Any], list[float]] | None = None
    for index, alpha in enumerate(candidates):
        candidate_model = _fit_ridge(train_rows, alpha, units, version)
        predictions = [predict_from_features(row["features"], candidate_model) for row in validation_rows]
        metrics = _metric_for_rows(validation_rows, predictions, units)
        val_results.append({"alpha": alpha, "metrics": metrics})
        # Candidate ordering resolves exact ties reproducibly.
        if best is None or metrics["mae"] < best[0]:
            best = (metrics["mae"], index, candidate_model, predictions)
    assert best is not None
    chosen_alpha = candidates[best[1]]
    model = best[2]

    # The test set is accessed only after alpha is selected and the final
    # train-only artifact is fixed. Every method below uses the identical rows.
    test_predictions = [predict_from_features(row["features"], model) for row in test_rows]
    test_metrics = {
        "ridge": _metric_for_rows(test_rows, test_predictions, units),
        "persistence": _metric_for_rows(
            test_rows, [row["baselines"]["persistence"] for row in test_rows], units,
        ),
        "seasonal_naive": _metric_for_rows(
            test_rows, [row["baselines"]["seasonal_naive"] for row in test_rows], units,
        ),
    }
    validation_metrics = val_results[best[1]]["metrics"]
    metadata: dict[str, Any] = {
        "model_version": version,
        "algorithm_version": MODEL_ALGORITHM_VERSION,
        "location_id": LOCATION_ID,
        "variable": VARIABLE,
        "target_definition": "daily T2M for target_date; one daily step after the latest archive date",
        "units": units,
        "disclaimer": DISCLAIMER,
        "train_timestamp": timestamp,
        "sources": list(sources or []),
        "periods": {
            "train": _period_summary(train_rows),
            "validation": _period_summary(validation_rows),
            "test": _period_summary(test_rows),
        },
        "counts": {name: len(partitions[name]) for name in ("train", "validation", "test")},
        "alpha_candidates": candidates,
        "validation_alpha_results": val_results,
        "selected_alpha": chosen_alpha,
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "test_comparison_note": "Ridge and both baselines use the exact same held-out test target rows.",
    }
    model["train_timestamp"] = timestamp
    model["training_period"] = metadata["periods"]["train"]

    if history_store is not None:
        try:
            store = _resolve_history_store(history_store)
            if store is None:
                metadata["persistence_warning"] = (
                    "HistoryStore is not available in this checkout; model and metadata were returned but not persisted."
                )
            else:
                persist_training_results(store, model, metadata)
                metadata["history_persisted"] = True
        except Exception as exc:
            # Persistence is optional and must not make the pure modeling path
            # unusable while another agent's HistoryStore is being integrated.
            metadata["history_persisted"] = False
            metadata["persistence_warning"] = f"HistoryStore persistence failed: {type(exc).__name__}: {exc}"
    return model, metadata


def save_model(model: Mapping[str, Any], path: str | os.PathLike[str]) -> Path:
    """Write a JSON-safe model artifact and return its destination."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(dict(model), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    return destination


def load_model(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load and validate a model JSON artifact."""
    with Path(path).open("r", encoding="utf-8") as handle:
        model = json.load(handle)
    if not isinstance(model, dict) or model.get("model_type") != "standardized_ridge_regression":
        raise ValueError("Not a supported standardized ridge model artifact")
    if model.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("Model artifact has incompatible feature names")
    # Validate shapes/scales using a finite zero vector.
    predict_from_features({name: 0.0 for name in FEATURE_NAMES}, model)
    return model


def save_metadata(metadata: Mapping[str, Any], path: str | os.PathLike[str]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(dict(metadata), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    return destination


def predict_series_next_day(
    series: Any,
    model_artifact: Mapping[str, Any] | str | os.PathLike[str],
    evaluation: Any = None,
) -> dict[str, Any]:
    """Pure predictor: estimate the day after the latest valid stored observation."""
    model = load_model(model_artifact) if isinstance(model_artifact, (str, os.PathLike)) else dict(model_artifact)
    # Validate model structure through the same artifact checks used by loading.
    if model.get("model_type") != "standardized_ridge_regression":
        raise ValueError("Unsupported or invalid model artifact")
    if model.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("Model artifact has incompatible feature names")
    values = _normalise_series(series)
    available = [day for day, value in values.items() if value is not None]
    if not available:
        raise InsufficientDataError("No valid archived T2M values are available for prediction")
    as_of = max(available)
    target_day = as_of + timedelta(days=1)
    features = _features_for_target(values, target_day)
    if features is None:
        raise InsufficientDataError(
            f"Insufficient contiguous history as of {as_of.isoformat()}: prediction needs valid exact-date "
            "lags through 365 days and complete prior 30-day history."
        )
    value = predict_from_features(features, model)
    baselines = {
        "persistence": float(values[as_of]),
        "seasonal_naive": float(values[_target_year_previous_day(target_day)]),
    }
    if isinstance(evaluation, Mapping):
        evaluation_result = {
            "validation_metrics": evaluation.get("validation_metrics"),
            "test_metrics": evaluation.get("test_metrics"),
            "evaluated_periods": evaluation.get("periods"),
        }
    else:
        evaluation_result = evaluation
    return {
        "target_date": target_day.isoformat(),
        "as_of": as_of.isoformat(),
        "prediction_value": value,
        "unit": model.get("units", DEFAULT_UNITS),
        "horizon_days": 1,
        "model_version": model.get("model_version"),
        "evaluation": evaluation_result,
        "baseline_values": baselines,
        "label": DISCLAIMER,
    }


# The following adapter is intentionally lazy: src/earthscope/history_store.py
# may be supplied by a separate integration task, and importing this module must
# work before then.
def _resolve_history_store(store_or_path: Any) -> Any:
    if not isinstance(store_or_path, (str, os.PathLike)):
        return store_or_path
    history_class = _history_store_class()
    if history_class is None:
        return None
    return history_class(path=str(store_or_path))


def _history_store_class() -> Any:
    """Resolve HistoryStore only at point of use, tolerating its absence."""
    for module_name in (
        "earthscope.history_store",
        "earthscope.history",
        "earthscope.history_db",
    ):
        try:
            return getattr(importlib.import_module(module_name), "HistoryStore")
        except (ImportError, AttributeError):
            continue
    return None


def _new_history_store(db_path: str | os.PathLike[str] | None = None) -> Any:
    history_class = _history_store_class()
    if history_class is None:
        raise RuntimeError(
            "HistoryStore is not available; install the history-store integration "
            "before using the database-backed train/predict API."
        )
    return history_class(path=None if db_path is None else str(db_path))


def _default_artifact_path() -> Path:
    return Path(__file__).resolve().parents[2] / "models" / "cairo_t2m_next_day.json"


def _resolve_metadata_path(metadata_path: str | os.PathLike[str] | None,
                           artifact_path: str | os.PathLike[str] | None = None) -> Path:
    if metadata_path is not None:
        return Path(metadata_path)
    artifact = Path(artifact_path) if artifact_path is not None else _default_artifact_path()
    return artifact.with_suffix(".metadata.json")


def load_model_metadata(metadata_path: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    """Load evaluation metadata JSON, or return ``None`` if it does not exist."""
    path = _resolve_metadata_path(metadata_path)
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    if not isinstance(metadata, dict):
        raise ValueError(f"Model metadata must be a JSON object: {path}")
    return metadata


def train_model(
    db_path: str | os.PathLike[str] | None = None,
    artifact_path: str | os.PathLike[str] | None = None,
    metadata_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Train from HistoryStore, persist model/evaluations, save JSON, return metadata."""
    store = _new_history_store(db_path)
    series = store.variable_series(LOCATION_ID, VARIABLE, start_date="1980-01-01", end_date="2025-12-31")
    if not series:
        raise InsufficientDataError(
            f"No {VARIABLE} history is available for {LOCATION_ID}; ingest the archive before training."
        )
    model, metadata = train_temperature_model(
        series,
        sources=[f"HistoryStore {db_path or os.environ.get('EARTHSCOPE_HISTORY_DB', 'default database')}: "
                 f"{LOCATION_ID}/{VARIABLE}"],
    )
    model_path = Path(artifact_path) if artifact_path is not None else _default_artifact_path()
    metadata_file = _resolve_metadata_path(metadata_path, model_path)
    metadata["artifact_path"] = str(model_path)
    metadata["metadata_path"] = str(metadata_file)
    try:
        persist_training_results(store, model, metadata)
        metadata["history_persisted"] = True
    except Exception as exc:
        metadata["history_persisted"] = False
        metadata["persistence_warning"] = f"HistoryStore persistence failed: {type(exc).__name__}: {exc}"
    save_model(model, model_path)
    save_metadata(metadata, metadata_file)
    return metadata


def predict_next_day(
    location_id: str = "cairo-eg",
    db_path: str | os.PathLike[str] | None = None,
    artifact_path: str | os.PathLike[str] | None = None,
    metadata_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Database-backed next-day prediction in the parent API/frontend schema."""
    store = _new_history_store(db_path)
    model_file = Path(artifact_path) if artifact_path is not None else _default_artifact_path()
    metadata_file = _resolve_metadata_path(metadata_path, model_file)
    model = load_model(model_file)
    metadata = load_model_metadata(metadata_file)
    series = store.variable_series(location_id, VARIABLE, start_date=None, end_date=None)
    raw_prediction = predict_series_next_day(series, model, evaluation=metadata)

    test_metrics = (metadata or {}).get("test_metrics", {})
    model_metrics = test_metrics.get("ridge") if isinstance(test_metrics, Mapping) else None
    evaluation = {
        "held_out_model_metrics": model_metrics,
        "period": (metadata or {}).get("periods", {}).get("test"),
        "sample_count": model_metrics.get("sample_count") if isinstance(model_metrics, Mapping) else None,
        "baseline_comparison": {
            "persistence": test_metrics.get("persistence") if isinstance(test_metrics, Mapping) else None,
            "seasonal_naive": test_metrics.get("seasonal_naive") if isinstance(test_metrics, Mapping) else None,
        },
        "validation_metrics": (metadata or {}).get("validation_metrics"),
        "units": (metadata or {}).get("units", model.get("units", DEFAULT_UNITS)),
    }
    result = {
        "location_id": location_id,
        "location_name": "Cairo, Egypt" if location_id == LOCATION_ID else location_id,
        "as_of": raw_prediction["as_of"],
        "target_date": raw_prediction["target_date"],
        "predicted_value": raw_prediction["prediction_value"],
        "unit": raw_prediction["unit"],
        "horizon_days": 1,
        "model_version": raw_prediction["model_version"],
        "evaluation": evaluation,
        "baseline_predictions": raw_prediction["baseline_values"],
        "caveats": [DISCLAIMER],
    }
    record_prediction = getattr(store, "record_prediction", None)
    if callable(record_prediction):
        record_prediction({
            "model_version_id": result["model_version"],
            "location_id": location_id,
            "variable_code": VARIABLE,
            "target_date": result["target_date"],
            "generated_at": _timestamp_now(),
            "horizon_days": result["horizon_days"],
            "predicted_value": result["predicted_value"],
            "unit": result["unit"],
            "metadata": {
                "as_of": result["as_of"],
                "evaluation": result["evaluation"],
                "baseline_predictions": result["baseline_predictions"],
                "caveats": result["caveats"],
            },
        })
    return result


def _call_history_method(method: Any, payload: dict[str, Any], aliases: Mapping[str, tuple[str, ...]]) -> Any:
    """Pass only parameters accepted by a store method, accommodating interface revisions."""
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return method(**payload)
    parameters = signature.parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return method(**payload)

    kwargs: dict[str, Any] = {}
    positional: list[Any] = []
    for name, parameter in parameters.items():
        if name in ("self", "cls"):
            continue
        lookup_names = (name,) + tuple(aliases.get(name, ()))
        found = next((payload[key] for key in lookup_names if key in payload), None)
        has_value = any(key in payload for key in lookup_names)
        if not has_value:
            if parameter.default is inspect.Parameter.empty and parameter.kind not in (
                inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD,
            ):
                raise TypeError(f"Cannot map required HistoryStore parameter {name!r}")
            continue
        if parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
            positional.append(found)
        elif parameter.kind != inspect.Parameter.VAR_POSITIONAL:
            kwargs[name] = found
    return method(*positional, **kwargs)


def persist_training_results(store: Any, model: Mapping[str, Any], metadata: Mapping[str, Any]) -> None:
    """Persist model-version metadata and validation/test evaluations via store API."""
    model_payload = {
        "model_version": model["model_version"],
        "model_version_id": model["model_version"],
        "model_name": "cairo_t2m_next_day",
        "version": model["model_version"],
        "training_start": metadata.get("periods", {}).get("train", {}).get("start"),
        "training_end": metadata.get("periods", {}).get("train", {}).get("end"),
        "location_id": metadata.get("location_id", LOCATION_ID),
        "variable": metadata.get("variable", VARIABLE),
        "model_type": model.get("model_type"),
        "algorithm_version": model.get("algorithm_version"),
        "alpha": model.get("alpha"),
        "artifact": dict(model),
        "model": dict(model),
        "metadata": dict(metadata),
        "train_timestamp": metadata.get("train_timestamp"),
        "created_at": metadata.get("train_timestamp"),
    }
    register_version = getattr(store, "register_model_version", None)
    register_evaluation = getattr(store, "register_evaluation", None)
    if not callable(register_version) or not callable(register_evaluation):
        raise AttributeError("HistoryStore must provide register_model_version and register_evaluation")
    aliases = {
        "version": ("model_version",),
        "model": ("artifact",),
        "artifact": ("model",),
        "model_path": ("artifact_path",),
        "created_at": ("train_timestamp",),
        "timestamp": ("train_timestamp",),
        "record": ("metadata",),
    }
    _call_history_method(register_version, model_payload, aliases)

    for split_name, metrics in (
        ("validation", metadata.get("validation_metrics")),
        ("test", metadata.get("test_metrics")),
    ):
        evaluation_payload = {
            "model_version": model["model_version"],
            "model_version_id": model["model_version"],
            "version": model["model_version"],
            "location_id": metadata.get("location_id", LOCATION_ID),
            "variable": metadata.get("variable", VARIABLE),
            "split": split_name,
            "evaluation_name": split_name,
            "evaluation_type": split_name,
            "evaluated_at": metadata.get("train_timestamp", _timestamp_now()),
            "metrics": metrics,
            "results": metrics,
            "evaluation": metrics,
            "metadata": dict(metadata),
            "record": {
                "model_version": model["model_version"],
                "location_id": metadata.get("location_id", LOCATION_ID),
                "variable": metadata.get("variable", VARIABLE),
                "split": split_name,
                "metrics": metrics,
            },
            "period": metadata.get("periods", {}).get(split_name),
            "created_at": metadata.get("train_timestamp"),
        }
        evaluation_aliases = {
            "version": ("model_version",),
            "evaluation_type": ("split",),
            "split_name": ("split",),
            "results": ("metrics",),
            "evaluation": ("metrics",),
            "record": (),
            "created_at": ("train_timestamp",),
            "timestamp": ("created_at",),
        }
        _call_history_method(register_evaluation, evaluation_payload, evaluation_aliases)
