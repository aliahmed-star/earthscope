import os
import sys
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import api as api_module  # noqa: E402
from earthscope.history_store import HistoryStore  # noqa: E402

client = TestClient(api_module.app)


@pytest.fixture
def archived_cairo(tmp_path, monkeypatch):
    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("EARTHSCOPE_HISTORY_DB", str(db_path))
    records = []
    definitions = [
        ("T2M", 20.0, "°C", "°C"),
        ("RH2M", 55.0, "%", "%"),
        ("WS10M", 2.0, "m/s", "km/h"),
        ("PRECTOTCORR", 0.0, "mm/day", "mm/day"),
    ]
    for offset in range(2):
        day = date(2024, 1, 1) + timedelta(days=offset)
        for code, base, raw_unit, canonical_unit in definitions:
            raw_value = base + offset
            normalized = raw_value * 3.6 if code == "WS10M" else raw_value
            records.append({
                "location_id": "cairo-eg",
                "dataset_id": "NASA_POWER_DAILY",
                "variable_code": code,
                "observed_on": day.isoformat(),
                "resolution": "daily",
                "raw_value": raw_value,
                "raw_unit": raw_unit,
                "normalized_value": normalized,
                "canonical_unit": canonical_unit,
                "source_metadata": {
                    "api_name": "POWER Daily API", "api_version": "test",
                    "time_standard": "UTC", "community": "RE",
                },
            })
    with HistoryStore(db_path) as store:
        store.upsert_observations(records)
    return db_path


def test_history_availability_and_observation_query_are_persisted_and_filtered(archived_cairo):
    available = client.get("/api/history/availability")
    assert available.status_code == 200
    payload = available.json()
    assert payload["total_observation_rows"] == 8
    cairo = next(item for item in payload["coverage"] if item["location_id"] == "cairo-eg")
    assert (cairo["min_date"], cairo["max_date"]) == ("2024-01-01", "2024-01-02")

    response = client.get("/api/history/observations", params={
        "location_id": "cairo-eg", "variable": "wind_speed_kmh",
        "start_date": "2024-01-02", "end_date": "2024-01-02", "resolution": "daily",
    })
    assert response.status_code == 200
    result = response.json()
    assert result["variable"] == "wind_speed_kmh"
    assert result["rows"] == [{
        "observed_on": "2024-01-02", "value": 10.8, "raw_value": 3.0,
        "raw_unit": "m/s", "unit": "km/h", "source": "NASA_POWER_DAILY",
        "dataset_id": "NASA_POWER_DAILY", "ingested_at": result["rows"][0]["ingested_at"],
        "raw_response_path": None, "raw_sha256": None,
        "metadata": {"api_name": "POWER Daily API", "api_version": "test",
                     "time_standard": "UTC", "community": "RE"},
    }]


def test_history_query_rejects_invalid_location_date_order_and_oversized_window(archived_cairo):
    assert client.get("/api/history/observations", params={
        "location_id": "unknown", "variable": "T2M",
        "start_date": "2024-01-01", "end_date": "2024-01-02",
    }).status_code == 422
    assert client.get("/api/history/observations", params={
        "location_id": "cairo-eg", "variable": "T2M",
        "start_date": "2024-01-03", "end_date": "2024-01-02",
    }).status_code == 422
    assert client.get("/api/history/observations", params={
        "location_id": "cairo-eg", "variable": "T2M",
        "start_date": "1981-01-01", "end_date": "2026-09-14",
    }).status_code == 422


def test_historical_dashboard_returns_archive_values_and_matching_summary(archived_cairo):
    response = client.get("/api/dashboard", params={
        "mode": "historical", "stations": ["cairo-eg"],
        "start_date": "2024-01-01", "end_date": "2024-01-02",
    })
    assert response.status_code == 200
    dashboard = response.json()
    assert dashboard["mode"] == "historical"
    assert dashboard["requested_mode"] == "historical"
    assert dashboard["is_simulated"] is False
    assert dashboard["range"] == {"start": "2024-01-01", "end": "2024-01-02"}
    assert dashboard["series"]["cairo-eg"]["temperature"] == [20.0, 21.0]
    assert dashboard["series"]["cairo-eg"]["wind"] == [7.2, 10.8]
    assert dashboard["incidents"] == []
    summary = dashboard["graph_summaries"]["variables"]["temperature"]["locations"][0]
    assert summary["count"] == 2 and summary["mean"] == 20.5
    assert summary["min"] == {"date": "2024-01-01", "value": 20.0}

    summarized = client.get("/api/graph-summaries", params={
        "mode": "historical", "stations": ["cairo-eg"],
        "start_date": "2024-01-02", "end_date": "2024-01-02",
    })
    assert summarized.status_code == 200
    item = summarized.json()["graph_summaries"]["variables"]["temperature"]["locations"][0]
    assert item["count"] == 1 and item["mean"] == 21.0


def test_historical_dashboard_rejects_more_than_ten_years_and_missing_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("EARTHSCOPE_HISTORY_DB", str(tmp_path / "empty.sqlite3"))
    too_long = client.get("/api/dashboard", params={
        "mode": "historical", "stations": ["cairo-eg"],
        "start_date": "1981-01-01", "end_date": "2026-09-14",
    })
    assert too_long.status_code == 422
    missing = client.get("/api/dashboard", params={
        "mode": "historical", "stations": ["cairo-eg"],
        "start_date": "2024-01-01", "end_date": "2024-01-02",
    })
    assert missing.status_code == 503


def test_model_status_evaluation_and_prediction_api_shapes(monkeypatch):
    metadata = {
        "model_version": "cairo-test-v1", "algorithm_version": "standardized-ridge-v1",
        "location_id": "cairo-eg", "variable": "T2M", "units": "°C",
        "periods": {"train": {"start": "1981-01-01", "end": "2019-12-31"},
                    "validation": {"start": "2020-01-01", "end": "2022-12-31"},
                    "test": {"start": "2023-01-01", "end": "2025-12-31"}},
        "counts": {"train": 14000, "validation": 1095, "test": 1095},
        "validation_metrics": {"mae": 1.2}, "test_metrics": {"ridge": {"mae": 1.3}},
        "test_comparison_note": "same dates", "disclaimer": "not a forecast",
    }
    prediction = {
        "location_id": "cairo-eg", "location_name": "Cairo, Egypt",
        "as_of": "2026-09-14", "target_date": "2026-09-15", "predicted_value": 28.4,
        "unit": "°C", "horizon_days": 1, "model_version": "cairo-test-v1",
        "evaluation": {"held_out_model_metrics": {"mae": 1.3}, "sample_count": 1095},
        "baseline_predictions": {"persistence": 27.8, "seasonal_naive": 27.0},
        "caveats": ["not a forecast"],
    }
    monkeypatch.setattr(api_module, "load_model_metadata", lambda: metadata)
    monkeypatch.setattr(api_module, "predict_next_day", lambda location_id="cairo-eg": prediction)

    status = client.get("/api/model/status")
    assert status.status_code == 200 and status.json()["available"] is True
    evaluation = client.get("/api/model/evaluation")
    assert evaluation.status_code == 200
    assert evaluation.json()["periods"]["test"] == metadata["periods"]["test"]
    result = client.get("/api/predictions/next-day")
    assert result.status_code == 200
    assert result.json() == prediction
    assert client.get("/api/predictions/next-day", params={"location_id": "tokyo-jp"}).status_code == 422
