import gzip
import hashlib
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from earthscope.history_ingest import (
    HistoryIngestError,
    conservative_end_date,
    date_chunks,
    fetch_with_retries,
    ingest_history,
)
from earthscope.history_store import HistoryStore, MIGRATION_PATH
from earthscope.providers.nasa_power import NasaPowerError


LOCATION = {
    "location_id": "cairo-eg", "location_name": "Cairo, Egypt",
    "latitude": 30.0444, "longitude": 31.2357,
}
PARAMETERS = ["T2M", "RH2M", "WS10M", "PRECTOTCORR"]


def make_payload(start_date="20240101", end_date="20240103"):
    start = date.fromisoformat(f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}")
    end = date.fromisoformat(f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}")
    keys = []
    cursor = start
    while cursor <= end:
        keys.append(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=1)
    return {
        "type": "Feature",
        "properties": {"parameter": {
            "T2M": {key: (12.5 if i != 1 else -999.0) for i, key in enumerate(keys)},
            "RH2M": {key: 66.0 + i for i, key in enumerate(keys)},
            "WS10M": {key: 2.5 for key in keys},
            "PRECTOTCORR": {key: 0.0 if i == 0 else 1.25 for i, key in enumerate(keys)},
        }},
        "header": {
            "time_standard": "UTC", "community": "RE", "sources": ["POWER"],
            "api": {"name": "POWER Daily API", "version": "v2.test"},
        },
        "parameters": {
            "T2M": {"longname": "Temperature", "units": "C"},
            "RH2M": {"longname": "Relative Humidity", "units": "%"},
            "WS10M": {"longname": "Wind Speed", "units": "m/s"},
            "PRECTOTCORR": {"longname": "Corrected precipitation", "units": "mm/day"},
        },
    }


def test_migration_indexes_foreign_keys_and_idempotent_observation_upsert(tmp_path):
    db = tmp_path / "history.sqlite3"
    store = HistoryStore(db)
    row = {
        "location_id": LOCATION["location_id"], "variable_code": "WS10M", "observed_on": "2024-01-01",
        "raw_value": 3.0, "raw_unit": "m/s", "normalized_value": 10.8, "canonical_unit": "km/h",
        "source_metadata": {"api_version": "test"}, "raw_response_path": "data/raw/sample.json.gz",
        "raw_sha256": "abc123",
    }
    assert store.upsert_observations([row]) == 1
    assert store.upsert_observations([dict(row, normalized_value=14.4, raw_value=4.0)]) == 1
    results = store.query_observations("cairo-eg", "wind_speed_kmh", "2024-01-01", "2024-01-01")
    assert len(results["rows"]) == 1
    assert results["rows"][0]["value"] == 14.4
    assert results["rows"][0]["raw_value"] == 4.0
    assert results["rows"][0]["metadata"] == {"api_version": "test"}
    assert store.availability()["total_observation_rows"] == 1

    conn = store._connection
    indexes = {row["name"] for row in conn.execute("PRAGMA index_list(observations)")}
    assert "idx_observations_location_variable_resolution_date" in indexes
    assert conn.execute("PRAGMA foreign_key_list(observations)").fetchall()
    with pytest.raises(Exception):
        store.upsert_observations([dict(row, location_id="no-such-location")])
    store.close()


def test_v1_database_migrates_to_shared_provenance_without_losing_history(tmp_path):
    db = tmp_path / "history-v1.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO locations(location_id, location_name, latitude, longitude) VALUES (?, ?, ?, ?)",
        ("cairo-eg", "Cairo, Egypt", 30.0444, 31.2357),
    )
    conn.execute(
        "INSERT INTO variables(variable_code, canonical_name, canonical_unit, raw_unit) VALUES (?, ?, ?, ?)",
        ("T2M", "temperature_c", "°C", "°C"),
    )
    conn.execute(
        "INSERT INTO datasets(dataset_id, source_code, resolution) VALUES (?, ?, ?)",
        ("NASA_POWER_DAILY", "NASA_POWER_DAILY", "daily"),
    )
    conn.execute(
        """INSERT INTO observations(location_id, dataset_id, variable_code, observed_on, resolution,
           raw_value, raw_unit, normalized_value, canonical_unit, source_metadata_json,
           raw_response_path, raw_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("cairo-eg", "NASA_POWER_DAILY", "T2M", "2024-01-01", "daily", 15.0, "°C", 15.0, "°C",
         json.dumps({"api_version": "v1", "raw_sha256": "legacy-sha"}), "raw/sample.json.gz", "legacy-sha"),
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    store = HistoryStore(db)
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert store._connection.execute("SELECT COUNT(*) FROM source_responses").fetchone()[0] == 1
    assert "source_response_id" in {
        row["name"] for row in store._connection.execute("PRAGMA table_info(observations)")
    }
    assert "source_metadata_json" not in {
        row["name"] for row in store._connection.execute("PRAGMA table_info(observations)")
    }
    result = store.query_observations("cairo-eg", "T2M", "2024-01-01", "2024-01-01")
    assert result["rows"][0]["value"] == 15.0
    assert result["rows"][0]["metadata"]["api_version"] == "v1"
    assert result["rows"][0]["raw_response_path"] == "raw/sample.json.gz"
    assert result["rows"][0]["raw_sha256"] == "legacy-sha"
    store.close()


def test_ingest_stores_complete_daily_rows_missing_fill_wind_conversion_and_raw_provenance(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return make_payload(kwargs["start_date"], kwargs["end_date"])

    result = ingest_history(
        "2024-01-01", "2024-01-03", locations=[LOCATION], store=store,
        fetch_func=fake_fetch, sleep_func=lambda _delay: None,
        raw_directory=tmp_path / "raw" / "nasa_power_history",
    )
    assert result["status"] == "completed"
    assert len(calls) == 1
    assert calls[0]["start_date"] == "20240101"
    assert calls[0]["end_date"] == "20240103"
    assert calls[0]["parameters"] == PARAMETERS
    assert store.availability()["total_observation_rows"] == 12

    temp = store.variable_series("cairo-eg", "T2M", "2024-01-01", "2024-01-03")
    assert temp == [
        {"date": "2024-01-01", "value": 12.5},
        {"date": "2024-01-02", "value": None},
        {"date": "2024-01-03", "value": 12.5},
    ]
    wind = store.query_observations("cairo-eg", "WS10M", "2024-01-01", "2024-01-03")
    assert [row["value"] for row in wind["rows"]] == [9.0, 9.0, 9.0]
    assert all(row["raw_value"] == 2.5 and row["unit"] == "km/h" for row in wind["rows"])

    archived = list((tmp_path / "raw" / "nasa_power_history").glob("*.json.gz"))
    assert len(archived) == 1
    raw_json = gzip.decompress(archived[0].read_bytes())
    assert json.loads(raw_json)["header"]["time_standard"] == "UTC"
    first_meta = wind["rows"][0]["metadata"]
    assert first_meta["raw_sha256"] == hashlib.sha256(raw_json).hexdigest()
    assert first_meta["raw_response_path"].endswith(archived[0].name)

    coverage = next(item for item in store.availability()["coverage"] if item["location_id"] == "cairo-eg")
    assert (coverage["min_date"], coverage["max_date"]) == ("2024-01-01", "2024-01-03")
    t2m = next(variable for variable in coverage["variables"] if variable["variable_code"] == "T2M")
    assert t2m["record_count"] == 3 and t2m["missing_count"] == 1

    dashboard = store.dashboard_observations(["cairo-eg"], "2024-01-01", "2024-01-03")
    assert len(dashboard) == 3
    assert dashboard[0]["observed_at"] == "2024-01-01T00:00:00Z"
    assert dashboard[0]["wind_speed_kmh"] == 9.0
    assert dashboard[0]["rainfall_mm"] == 0.0
    assert dashboard[0]["data_source"] == "NASA_POWER_DAILY"
    assert dashboard[0]["is_simulated"] is False
    store.close()


def test_idempotent_reingest_and_update_overlap(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    requests = []

    def fake_fetch(**kwargs):
        requests.append(kwargs)
        return make_payload(kwargs["start_date"], kwargs["end_date"])

    ingest_history("2024-01-01", "2024-01-10", locations=[LOCATION], store=store,
                   fetch_func=fake_fetch, raw_directory=tmp_path / "raw")
    assert store.availability()["total_observation_rows"] == 10 * 4

    result = ingest_history("2024-01-01", "2024-01-10", locations=[LOCATION], store=store,
                            update=True, fetch_func=fake_fetch, raw_directory=tmp_path / "raw")
    assert result["requests"] == 1
    assert requests[-1]["start_date"] == "20240103"  # seven-day overlap before latest coverage
    assert store.availability()["total_observation_rows"] == 10 * 4

    # A newer end date refreshes the tail from seven-day overlap and leaves one natural row per key.
    result = ingest_history("2024-01-01", "2024-01-12", locations=[LOCATION], store=store,
                            update=True, fetch_func=fake_fetch, raw_directory=tmp_path / "raw")
    assert result["requests"] == 1
    assert requests[-1]["start_date"] == "20240103"
    assert store.availability()["total_observation_rows"] == 12 * 4
    store.close()


def test_date_chunks_are_inclusive_and_maximum_five_years():
    chunks = date_chunks("1981-01-01", "1992-12-31")
    assert chunks[0] == (date(1981, 1, 1), date(1985, 12, 31))
    assert chunks[-1][1] == date(1992, 12, 31)
    for start, end in chunks:
        assert end < date(start.year + 5, start.month, start.day)
    assert conservative_end_date(date(2026, 11, 14)) == date(2026, 9, 15)


def test_retry_only_transient_errors_and_at_most_four_attempts():
    delays = []
    attempts = {"count": 0}

    def transient_then_ok(**_kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise NasaPowerError("NASA POWER API returned HTTP status 503")
        return {"ok": True}

    result = fetch_with_retries(transient_then_ok, fetch_kwargs={}, sleep_func=delays.append)
    assert result == {"ok": True}
    assert attempts["count"] == 3
    assert delays == [1.0, 2.0]

    attempts["count"] = 0
    delays.clear()

    def permanent(**_kwargs):
        attempts["count"] += 1
        raise NasaPowerError("NASA POWER API returned HTTP status 400")

    with pytest.raises(NasaPowerError):
        fetch_with_retries(permanent, fetch_kwargs={}, sleep_func=delays.append)
    assert attempts["count"] == 1
    assert delays == []

    attempts["count"] = 0

    def always_timeout(**_kwargs):
        attempts["count"] += 1
        raise TimeoutError("request timed out")

    with pytest.raises(TimeoutError):
        fetch_with_retries(always_timeout, fetch_kwargs={}, sleep_func=delays.append)
    assert attempts["count"] == 4


def test_dry_run_does_not_fetch_or_create_database(tmp_path):
    database_path = tmp_path / "not-created.db"
    store = HistoryStore(database_path)
    store.close()
    database_path.unlink()
    result = ingest_history("1981-01-01", "1990-12-31", locations=[LOCATION], dry_run=True,
                            fetch_func=lambda **_: pytest.fail("dry run must not fetch"))
    assert result["status"] == "dry_run"
    assert result["requests_planned"] == 2
    assert not database_path.exists()


def test_model_version_evaluation_and_prediction_are_idempotent(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    version_id = store.register_model_version({
        "model_name": "heat-risk", "version": "1.0", "training_start": "2020-01-01",
        "metadata": {"algorithm": "test"},
    })
    assert version_id == "heat-risk:1.0"
    assert store.register_model_version(model_name="heat-risk", version="1.0") == version_id

    first_eval = store.register_evaluation({
        "model_version_id": version_id, "evaluation_name": "holdout", "evaluated_at": "2024-01-01T00:00:00Z",
        "dataset_id": "test", "metrics": {"mae": 1.2},
    })
    repeated_eval = store.register_evaluation({
        "model_version_id": version_id, "evaluation_name": "holdout", "evaluated_at": "2024-01-01T00:00:00Z",
        "dataset_id": "test", "metrics": {"mae": 1.0},
    })
    assert first_eval == repeated_eval
    assert store._connection.execute("SELECT COUNT(*) FROM model_evaluations").fetchone()[0] == 1

    prediction = {
        "model_version_id": version_id, "location_id": "cairo-eg", "variable": "temperature_c",
        "target_date": "2024-02-01", "horizon_days": 7, "predicted_value": 31.5,
    }
    prediction_id = store.record_prediction(prediction)
    assert store.record_prediction(dict(prediction, predicted_value=32.0)) == prediction_id
    assert store._connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1
    stored = store._connection.execute("SELECT predicted_value, unit FROM predictions").fetchone()
    assert tuple(stored) == (32.0, "°C")
    store.close()


def test_malformed_non_utc_payload_fails_without_retry(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        payload = make_payload(kwargs["start_date"], kwargs["end_date"])
        payload["header"]["time_standard"] = "LST"
        return payload

    with pytest.raises(NasaPowerError, match="Expected NASA POWER UTC"):
        ingest_history("2024-01-01", "2024-01-01", locations=[LOCATION], store=store,
                       fetch_func=fetch, sleep_func=lambda _delay: None, raw_directory=tmp_path / "raw")
    assert len(calls) == 1
    store.close()
