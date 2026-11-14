from datetime import date, timedelta

import numpy as np
import pytest

from earthscope import prediction_model as prediction_module
from earthscope.prediction_model import (
    FEATURE_NAMES,
    InsufficientDataError,
    build_training_rows,
    calculate_metrics,
    chronological_split,
    load_model,
    predict_series_next_day,
    save_model,
    save_metadata,
    train_temperature_model,
)


def daily_history(start="2019-01-01", end="2024-12-31"):
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    records = []
    current = first
    index = 0
    while current <= last:
        # Smooth annual cycle plus short- and long-term variation, resembling
        # daily temperature without relying on a downloaded dataset.
        annual = 12.0 * np.sin(2 * np.pi * (current.timetuple().tm_yday - 1) / 365.2425)
        value = 22.0 + annual + 0.0008 * index + 1.3 * np.sin(index / 9.0)
        records.append({"date": current.isoformat(), "value": float(value)})
        current += timedelta(days=1)
        index += 1
    return records


def fit_small_custom_model(history=None):
    history = history or daily_history()
    return train_temperature_model(
        history,
        alpha_candidates=[0.1, 1.0, 10.0],
        split_periods={
            "train": ("2020-01-01", "2020-12-31"),
            "validation": ("2021-01-01", "2021-12-31"),
            "test": ("2022-01-01", "2022-12-31"),
        },
        train_timestamp="2026-11-14T00:00:00Z",
    )


def test_default_chronological_split_has_expected_nonoverlapping_periods():
    rows = [
        {"target_date": "2019-12-31"},
        {"target_date": "2020-01-01"},
        {"target_date": "2022-12-31"},
        {"target_date": "2023-01-01"},
        {"target_date": "2025-12-31"},
    ]
    split = chronological_split(rows)
    assert [r["target_date"] for r in split["train"]] == ["2019-12-31"]
    assert [r["target_date"] for r in split["validation"]] == ["2020-01-01", "2022-12-31"]
    assert [r["target_date"] for r in split["test"]] == ["2023-01-01", "2025-12-31"]


def test_custom_split_is_exact_and_rejects_overlap():
    rows = [{"target_date": f"2020-01-{day:02d}"} for day in range(1, 7)]
    custom = {
        "train": ("2020-01-01", "2020-01-02"),
        "validation": ("2020-01-03", "2020-01-04"),
        "test": ("2020-01-05", "2020-01-06"),
    }
    assert {key: len(value) for key, value in chronological_split(rows, custom).items()} == {
        "train": 2, "validation": 2, "test": 2
    }
    overlapping = dict(custom, validation=("2020-01-02", "2020-01-04"))
    with pytest.raises(ValueError, match="chronological"):
        chronological_split(rows, overlapping)


def test_feature_rows_do_not_use_target_or_future_values():
    history = daily_history()
    target_date = "2022-06-01"
    original = next(row for row in build_training_rows(history) if row["target_date"] == target_date)
    changed = [dict(record) for record in history]
    for record in changed:
        if record["date"] >= target_date:
            record["value"] += 10000.0
    altered = next(row for row in build_training_rows(changed) if row["target_date"] == target_date)
    assert altered["features"] == original["features"]
    assert altered["target"] != original["target"]
    assert set(original["features"]) == set(FEATURE_NAMES)
    assert original["features"]["lag_1"] == pytest.approx(
        next(item["value"] for item in history if item["date"] == "2022-05-31")
    )


def test_metrics_and_test_baselines_use_the_same_rows():
    metrics = calculate_metrics([1, 2, 3], [2, 2, 4], dates=["2020-01-01", "2020-01-02", "2020-01-03"])
    assert metrics["mae"] == pytest.approx(2 / 3)
    assert metrics["rmse"] == pytest.approx(np.sqrt(2 / 3))
    assert metrics["bias"] == pytest.approx(2 / 3)
    assert metrics["r2"] == pytest.approx(0.0)
    assert metrics["sample_count"] == 3
    assert metrics["period"] == {"start": "2020-01-01", "end": "2020-01-03"}
    assert metrics["units"] == "°C"

    _, metadata = fit_small_custom_model()
    comparisons = metadata["test_metrics"]
    assert set(comparisons) == {"ridge", "persistence", "seasonal_naive"}
    assert {item["sample_count"] for item in comparisons.values()} == {metadata["counts"]["test"]}
    assert {tuple(item["period"].values()) for item in comparisons.values()} == {
        tuple(metadata["periods"]["test"].values())
    }
    assert all("mae" in item and "rmse" in item and "bias" in item and "r2" in item for item in comparisons.values())
    assert metadata["selected_alpha"] in metadata["alpha_candidates"]
    assert metadata["periods"]["train"]["end"] < metadata["periods"]["validation"]["start"]
    assert metadata["periods"]["validation"]["end"] < metadata["periods"]["test"]["start"]


def test_model_save_load_round_trip(tmp_path):
    model, _ = fit_small_custom_model()
    path = save_model(model, tmp_path / "cairo_model.json")
    loaded = load_model(path)
    assert loaded == model
    assert len(loaded["coefficients"]) == len(FEATURE_NAMES)
    assert loaded["alpha"] > 0
    assert len(loaded["feature_mean"]) == len(FEATURE_NAMES)
    assert len(loaded["feature_std"]) == len(FEATURE_NAMES)


def test_next_day_prediction_has_date_baselines_and_forecast_disclaimer():
    history = daily_history(end="2024-12-31")
    model, metadata = fit_small_custom_model(history)
    result = predict_series_next_day(history, model, evaluation=metadata)
    assert result["target_date"] == "2025-01-01"
    assert result["as_of"] == "2024-12-31"
    assert result["horizon_days"] == 1
    assert result["model_version"] == metadata["model_version"]
    assert result["unit"] == "°C"
    assert np.isfinite(result["prediction_value"])
    assert set(result["baseline_values"]) == {"persistence", "seasonal_naive"}
    assert result["baseline_values"]["persistence"] == history[-1]["value"]
    assert "not an operational weather forecast" in result["label"].lower()
    assert result["evaluation"]["test_metrics"] == metadata["test_metrics"]


def test_missing_rows_are_dropped_and_insufficient_history_is_clear():
    history = daily_history(start="2020-01-01", end="2020-04-30")
    # No complete 365-day lag is available, so there are no trainable rows.
    assert build_training_rows(history) == []
    model, _ = fit_small_custom_model()
    with pytest.raises(InsufficientDataError, match="Insufficient contiguous history"):
        predict_series_next_day(history, model)
    with pytest.raises(InsufficientDataError, match="No valid archived"):
        predict_series_next_day([{"date": "2024-01-01", "value": None}], model)


def test_parent_database_prediction_contract(tmp_path, monkeypatch):
    history = daily_history(end="2024-12-31")
    model, metadata = fit_small_custom_model(history)
    model_path = save_model(model, tmp_path / "ridge.json")
    metadata_path = save_metadata(metadata, tmp_path / "ridge.metadata.json")

    class FakeHistoryStore:
        def __init__(self, path=None):
            self.path = path

        def variable_series(self, location_id, variable, start_date=None, end_date=None):
            assert location_id == "cairo-eg" and variable == "T2M"
            return history

    monkeypatch.setattr(prediction_module, "_history_store_class", lambda: FakeHistoryStore)
    result = prediction_module.predict_next_day(
        location_id="cairo-eg",
        db_path="test-history.sqlite",
        artifact_path=model_path,
        metadata_path=metadata_path,
    )
    assert set(result) == {
        "location_id", "location_name", "as_of", "target_date", "predicted_value",
        "unit", "horizon_days", "model_version", "evaluation", "baseline_predictions", "caveats",
    }
    assert result["location_id"] == "cairo-eg"
    assert result["location_name"] == "Cairo, Egypt"
    assert result["target_date"] == "2025-01-01" and result["horizon_days"] == 1
    assert result["evaluation"]["held_out_model_metrics"] == metadata["test_metrics"]["ridge"]
    assert result["evaluation"]["baseline_comparison"]["persistence"] == metadata["test_metrics"]["persistence"]
    assert set(result["baseline_predictions"]) == {"persistence", "seasonal_naive"}
    assert result["caveats"] and "not an operational weather forecast" in result["caveats"][0]


def test_constant_target_r2_is_reported_as_undefined():
    result = calculate_metrics([3, 3, 3], [3, 4, 2])
    assert result["r2"] is None
