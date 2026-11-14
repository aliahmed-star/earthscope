"""Per-location and per-variable one-day estimates with chronological evaluation.

The output is a statistical archive-origin estimate, not an operational forecast.
Each series has an early training window, a method-selection year, a separate
interval-calibration window, and a later held-out test window.
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from earthscope.history_store import DEFAULT_DB_PATH, HistoryStore, VARIABLES
from earthscope.prediction_model import (
    InsufficientDataError,
    _features_for_target,
    _fit_ridge,
    build_training_rows,
    calculate_metrics,
    predict_from_features,
)
from earthscope.providers.nasa_power import DEFAULT_LOCATIONS

ALGORITHM_VERSION = "standardized-ridge-plus-chronological-baselines-v1"
MODEL_BUNDLE_PATH = Path(__file__).resolve().parents[2] / "models" / "climate_models.json"
TRAIN_END = date(2019, 12, 31)
SELECT_START, SELECT_END = date(2020, 1, 1), date(2020, 12, 31)
CAL_START, CAL_END = date(2021, 1, 1), date(2022, 12, 31)
TEST_START, TEST_END = date(2023, 1, 1), date(2025, 12, 31)
NOMINAL_COVERAGE = 0.90
MIN_DISPLAYABLE_TEST_N = 100
DISPLAY_COVERAGE_BOUNDS = (0.85, 0.95)
UNITS = {code: unit for code, _name, unit, _raw, _desc in VARIABLES}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bound(value: float, variable: str) -> float:
    if variable in {"RH2M", "WS10M", "PRECTOTCORR"}:
        value = max(0.0, value)
    if variable == "RH2M":
        value = min(100.0, value)
    return float(value)


def _metrics(rows: list[dict[str, Any]], predictions: list[float], variable: str) -> dict[str, Any]:
    return calculate_metrics(
        [row["target"] for row in rows], predictions,
        [row["target_date"] for row in rows], UNITS[variable],
    )


def _conformal_radius(residuals: list[float], coverage: float = NOMINAL_COVERAGE) -> float:
    if not residuals:
        raise InsufficientDataError("No interval-calibration residuals are available")
    ordered = sorted(abs(float(item)) for item in residuals)
    # Split-conformal finite-sample order statistic: ceil((n + 1) * coverage).
    import math as _math
    rank = min(len(ordered), max(1, _math.ceil((len(ordered) + 1) * coverage)))
    return float(ordered[rank - 1])


def _period_rows(rows: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [row for row in rows if start <= date.fromisoformat(row["target_date"]) <= end]


def _ridge_values(rows: list[dict[str, Any]], model: Mapping[str, Any], variable: str) -> list[float]:
    return [_bound(predict_from_features(row["features"], model), variable) for row in rows]


def train_suite(
    db_path: str | os.PathLike[str] | None = None,
    output_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Train/evaluate every available default-location × NASA POWER variable."""
    path = Path(db_path) if db_path else Path(os.environ.get("EARTHSCOPE_HISTORY_DB", DEFAULT_DB_PATH))
    destination = Path(output_path) if output_path else MODEL_BUNDLE_PATH
    store = HistoryStore(path)
    entries: dict[str, dict[str, Any]] = {}
    try:
        for location in DEFAULT_LOCATIONS:
            for variable in (item[0] for item in VARIABLES):
                key = f"{location['location_id']}|{variable}"
                records = store.variable_series(location["location_id"], variable)
                try:
                    rows = build_training_rows(records)
                    train_rows = [row for row in rows if date.fromisoformat(row["target_date"]) <= TRAIN_END]
                    select_rows = _period_rows(rows, SELECT_START, SELECT_END)
                    calibration_rows = _period_rows(rows, CAL_START, CAL_END)
                    test_rows = _period_rows(rows, TEST_START, TEST_END)
                    if min(len(train_rows), len(select_rows), len(calibration_rows), len(test_rows)) == 0:
                        raise InsufficientDataError("Not enough rows in one or more chronological partitions")
                    if len(train_rows) < 365 or len(select_rows) < 60 or len(calibration_rows) < 100 or len(test_rows) < 100:
                        raise InsufficientDataError(
                            f"Minimum sample requirements not met: train={len(train_rows)}, "
                            f"selection={len(select_rows)}, calibration={len(calibration_rows)}, test={len(test_rows)}"
                        )
                    model_version = f"climate-ridge-v1-{location['location_id']}-{variable.lower()}"
                    model = _fit_ridge(train_rows, 1.0, UNITS[variable], model_version)
                    model["lower_bound"] = 0.0 if variable in {"RH2M", "WS10M", "PRECTOTCORR"} else None
                    model["upper_bound"] = 100.0 if variable == "RH2M" else None
                    selection = {
                        "ridge": _ridge_values(select_rows, model, variable),
                        "persistence": [_bound(float(row["baselines"]["persistence"]), variable) for row in select_rows],
                        "seasonal_naive": [_bound(float(row["baselines"]["seasonal_naive"]), variable) for row in select_rows],
                    }
                    selection_metrics = {name: _metrics(select_rows, values, variable) for name, values in selection.items()}
                    chosen_method = min(selection_metrics, key=lambda name: (selection_metrics[name]["mae"], name))
                    calibration_predictions = {
                        "ridge": _ridge_values(calibration_rows, model, variable),
                        "persistence": [_bound(float(row["baselines"]["persistence"]), variable) for row in calibration_rows],
                        "seasonal_naive": [_bound(float(row["baselines"]["seasonal_naive"]), variable) for row in calibration_rows],
                    }
                    calibration_residuals = [
                        prediction - float(row["target"])
                        for prediction, row in zip(calibration_predictions[chosen_method], calibration_rows)
                    ]
                    radius = _conformal_radius(calibration_residuals)
                    test_predictions = {
                        "ridge": _ridge_values(test_rows, model, variable),
                        "persistence": [_bound(float(row["baselines"]["persistence"]), variable) for row in test_rows],
                        "seasonal_naive": [_bound(float(row["baselines"]["seasonal_naive"]), variable) for row in test_rows],
                    }
                    test_metrics = {name: _metrics(test_rows, values, variable) for name, values in test_predictions.items()}
                    test_actual = [float(row["target"]) for row in test_rows]
                    intervals = []
                    for prediction in test_predictions[chosen_method]:
                        lower = prediction - radius
                        upper = prediction + radius
                        if variable in {"RH2M", "WS10M", "PRECTOTCORR"}:
                            lower = max(0.0, lower)
                        if variable == "RH2M":
                            upper = min(100.0, upper)
                        intervals.append((lower, upper))
                    covered = [lo <= actual <= hi for actual, (lo, hi) in zip(test_actual, intervals)]
                    heldout_coverage = sum(covered) / len(covered)
                    mean_width = sum(hi - lo for lo, hi in intervals) / len(intervals)
                    displayable = (
                        len(test_rows) >= MIN_DISPLAYABLE_TEST_N
                        and DISPLAY_COVERAGE_BOUNDS[0] <= heldout_coverage <= DISPLAY_COVERAGE_BOUNDS[1]
                    )
                    valid_dates = [date.fromisoformat(row["date"]) for row in records if row.get("value") is not None]
                    metadata = {
                        "status": "evaluated",
                        "location_id": location["location_id"], "location_name": location["location_name"],
                        "country_name": location.get("country_name", ""), "country_code": location.get("country_code", ""),
                        "variable_code": variable, "unit": UNITS[variable],
                        "model_version": model_version, "algorithm_version": ALGORITHM_VERSION,
                        "model_type": "standardized ridge regression with persistence and seasonal-naive comparisons",
                        "chosen_method": chosen_method,
                        "method_selection": {"period": {"start": SELECT_START.isoformat(), "end": SELECT_END.isoformat()},
                                             "metrics": selection_metrics},
                        "periods": {
                            "training": {"start": min(row["target_date"] for row in train_rows), "end": max(row["target_date"] for row in train_rows)},
                            "selection": {"start": min(row["target_date"] for row in select_rows), "end": max(row["target_date"] for row in select_rows)},
                            "calibration": {"start": min(row["target_date"] for row in calibration_rows), "end": max(row["target_date"] for row in calibration_rows)},
                            "test": {"start": min(row["target_date"] for row in test_rows), "end": max(row["target_date"] for row in test_rows)},
                        },
                        "counts": {"train": len(train_rows), "selection": len(select_rows),
                                   "calibration": len(calibration_rows), "test": len(test_rows)},
                        "test_metrics": test_metrics,
                        "baseline_comparison_note": "All three methods use the same chronological held-out target dates; method selection uses the separate 2020 selection period.",
                        "interval": {
                            "nominal_coverage": NOMINAL_COVERAGE,
                            "method": "symmetric split-conformal absolute residual quantile from the separate 2021-2022 calibration period",
                            "calibration_sample_count": len(calibration_rows),
                            "calibration_radius": radius,
                            "held_out_test_coverage": heldout_coverage,
                            "held_out_test_mean_width": mean_width,
                            "held_out_test_sample_count": len(test_rows),
                            "displayable": displayable,
                            "display_rule": "Shown only when held-out sample count is at least 100 and observed 2023-2025 coverage is 85%-95%; otherwise uncertainty is reported as not reliably quantified.",
                        },
                        "data_coverage": {"first_valid_date": min(valid_dates).isoformat() if valid_dates else None,
                                          "last_valid_date": max(valid_dates).isoformat() if valid_dates else None,
                                          "valid_observation_count": len(valid_dates)},
                        "disclaimer": "Archive-origin statistical estimate, not an operational weather forecast or disaster prediction.",
                    }
                    model["country_name"] = metadata["country_name"]
                    model["location_id"] = location["location_id"]
                    model["variable_code"] = variable
                    model["evaluation"] = metadata
                    entries[key] = {"model": model, "metadata": metadata}
                except (InsufficientDataError, ValueError, np.linalg.LinAlgError) as exc:
                    entries[key] = {
                        "model": None,
                        "metadata": {
                            "status": "insufficient_data", "location_id": location["location_id"],
                            "location_name": location["location_name"], "country_name": location.get("country_name", ""),
                            "country_code": location.get("country_code", ""), "variable_code": variable,
                            "unit": UNITS[variable], "warning": str(exc),
                            "disclaimer": "No estimate is produced when chronological evaluation requirements are not met.",
                        },
                    }
    finally:
        store.close()
    bundle = {
        "schema_version": 1, "built_at": _now(), "algorithm_version": ALGORITHM_VERSION,
        "dataset": "NASA POWER Daily Point API, UTC daily archive", "model_count": sum(1 for e in entries.values() if e["model"]),
        "entries": entries,
        "caveats": [
            "Results are estimates from historical daily NASA POWER grid-cell data, not operational forecasts.",
            "Ridge and both baselines use identical held-out test dates; the method is selected before calibration and test.",
            "Intervals are shown only if separate-calibration intervals attain the configured empirical held-out coverage range; even then they are not guarantees.",
            "Precipitation, wind, and humidity estimates are clipped only to physically admissible ranges after modeling.",
        ],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(bundle, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return {"path": str(destination), "model_count": bundle["model_count"], "entry_count": len(entries),
            "built_at": bundle["built_at"], "status_counts": {
                status: sum(1 for item in entries.values() if item["metadata"]["status"] == status)
                for status in sorted({item["metadata"]["status"] for item in entries.values()})
            }}


def load_bundle(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    filename = Path(path) if path else MODEL_BUNDLE_PATH
    if not filename.is_file():
        raise FileNotFoundError(f"Model suite not found: {filename}; run scripts/train_climate_models.py")
    bundle = json.loads(filename.read_text(encoding="utf-8"))
    if not isinstance(bundle.get("entries"), dict):
        raise ValueError("Model suite bundle is missing its entries map")
    return bundle


def predict_suite(
    location_ids: list[str] | None = None,
    db_path: str | os.PathLike[str] | None = None,
    bundle_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    bundle = load_bundle(bundle_path)
    selected = set(location_ids or [])
    store = HistoryStore(db_path)
    predictions = []
    try:
        locations = {item["location_id"]: item for item in DEFAULT_LOCATIONS}
        for key, entry in bundle["entries"].items():
            metadata = entry["metadata"]
            location_id = metadata["location_id"]
            if selected and location_id not in selected:
                continue
            model = entry.get("model")
            result = {**metadata}
            if not model:
                result.update({"prediction_status": "unavailable", "predicted_value": None})
                predictions.append(result)
                continue
            variable = metadata["variable_code"]
            series = store.variable_series(location_id, variable)
            valid_days = [date.fromisoformat(row["date"]) for row in series if row.get("value") is not None]
            if not valid_days:
                result.update({"prediction_status": "unavailable", "predicted_value": None,
                               "warning": "No usable archived observations are available."})
                predictions.append(result)
                continue
            as_of = max(valid_days)
            target = as_of + timedelta(days=1)
            values = {date.fromisoformat(row["date"]): row.get("value") for row in series}
            feature_map = _features_for_target(values, target)
            if feature_map is None:
                result.update({"prediction_status": "unavailable", "predicted_value": None,
                               "warning": f"Insufficient exact-date historical inputs as of {as_of.isoformat()}."})
                predictions.append(result)
                continue
            method = metadata["chosen_method"]
            if method == "ridge":
                value = _bound(predict_from_features(feature_map, model), variable)
            elif method == "persistence":
                value = _bound(float(values[as_of]), variable)
            else:
                try:
                    seasonal_day = target.replace(year=target.year - 1)
                except ValueError:
                    seasonal_day = target.replace(year=target.year - 1, day=28)
                seasonal = values.get(seasonal_day)
                if seasonal is None:
                    result.update({"prediction_status": "unavailable", "predicted_value": None,
                                   "warning": "Seasonal-naive value is missing for the same test/target date last year."})
                    predictions.append(result)
                    continue
                value = _bound(float(seasonal), variable)
            interval_info = metadata["interval"]
            interval = None
            if interval_info.get("displayable"):
                radius = float(interval_info["calibration_radius"])
                lower = value - radius
                upper = value + radius
                if variable in {"RH2M", "WS10M", "PRECTOTCORR"}:
                    lower = max(0.0, lower)
                if variable == "RH2M":
                    upper = min(100.0, upper)
                interval = {"level": 0.90, "lower": lower, "upper": upper,
                            "unit": metadata["unit"], "test_coverage": interval_info["held_out_test_coverage"],
                            "calibration_period": metadata["periods"]["calibration"],
                            "test_period": metadata["periods"]["test"]}
            latest_recorded = max((date.fromisoformat(row["date"]) for row in series), default=as_of)
            result.update({
                "prediction_status": "estimated", "predicted_value": value,
                "target_date": target.isoformat(), "as_of": as_of.isoformat(),
                "archive_latest_date": latest_recorded.isoformat(), "generated_at": _now(),
                "forecast_method": method, "prediction_interval": interval,
                "uncertainty_note": "Empirical interval withheld because its held-out coverage did not meet the display rule." if interval is None else
                                    "Empirical split-conformal range; held-out coverage is historical and the range is not a guarantee.",
                "disclaimer": "Historical-archive one-day estimate only; not an operational weather forecast and not a disaster prediction.",
            })
            predictions.append(result)
    finally:
        store.close()
    return {"generated_at": _now(), "model_bundle_built_at": bundle.get("built_at"),
            "dataset": bundle.get("dataset"), "predictions": predictions,
            "caveats": bundle.get("caveats", [])}
