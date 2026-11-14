"""
test_nasa_power.py - Comprehensive tests for NASA POWER API data provider.

Covers:
- Successful API response parsing and observation normalization.
- Unit conversion (WS10M m/s -> wind_speed_kmh km/h).
- Date parsing to ISO-8601 UTC string.
- NASA POWER fill value (-999.0) handled as None (never 0).
- Handling of missing / partial parameters in API payload.
- Handling of HTTP errors and network timeouts.
- Fallback to demo dataset via get_observations(provider=...).
- Preservation of is_simulated=False and data_source metadata.
- Full pipeline compatibility: nasa_power observations -> assess_all -> store.register_alerts.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock, patch
import pytest

from earthscope import config
from earthscope.data_loader import get_observations, validate_observation
from earthscope.analysis import assess_all, assess_observation
from earthscope.incidents import IncidentStore
from earthscope.providers.nasa_power import (
    NasaPowerError,
    clean_measurement,
    create_nasa_power_provider,
    fetch_nasa_power_point,
    normalize_nasa_power_records,
    DEFAULT_LOCATIONS,
)


SAMPLE_RAW_NASA_POWER_RESPONSE = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [31.2357, 30.0444, 23.0]},
    "properties": {
        "parameter": {
            "T2M": {"20240101": 15.2, "20240102": 16.0},
            "RH2M": {"20240101": 65.5, "20240102": 70.2},
            "WS10M": {"20240101": 3.0, "20240102": 5.5},  # 3.0 m/s = 10.8 km/h, 5.5 m/s = 19.8 km/h
            "PRECTOTCORR": {"20240101": 0.0, "20240102": 12.4},
        }
    },
    "header": {
        "title": "NASA/POWER Daily Data",
        "fill_value": -999.0,
        "time_standard": "UTC",
        "community": "RE",
        "sources": ["GEOSIT", "POWER"],
        "api": {"name": "POWER Daily API", "version": "v2.test"},
    },
    "parameters": {
        "T2M": {"longname": "Temperature at 2 Meters", "units": "C"},
        "RH2M": {"longname": "Relative Humidity at 2 Meters", "units": "%"},
        "WS10M": {"longname": "Wind Speed at 10 Meters", "units": "m/s"},
        "PRECTOTCORR": {"longname": "Precipitation Corrected", "units": "mm/day"},
    },
    "messages": []
}


def test_clean_measurement_valid_and_fill_values():
    assert clean_measurement(15.2) == 15.2
    assert clean_measurement("25.4") == 25.4
    assert clean_measurement(0.0) == 0.0
    # Fill values must return None, NEVER 0.0
    assert clean_measurement(-999.0) is None
    assert clean_measurement(-999) is None
    assert clean_measurement("-999.0") is None
    assert clean_measurement(None) is None
    assert clean_measurement("junk") is None


def test_normalize_nasa_power_records():
    records = normalize_nasa_power_records(
        raw_payload=SAMPLE_RAW_NASA_POWER_RESPONSE,
        location_id="cairo-eg",
        location_name="Cairo, Egypt",
        latitude=30.0444,
        longitude=31.2357,
    )
    assert len(records) == 2

    rec1 = records[0]
    assert rec1["location_id"] == "cairo-eg"
    assert rec1["location_name"] == "Cairo, Egypt"
    assert rec1["latitude"] == 30.0444
    assert rec1["longitude"] == 31.2357
    assert rec1["temperature_c"] == 15.2
    assert rec1["humidity_pct"] == 65.5
    # Unit conversion test: 3.0 m/s * 3.6 = 10.8 km/h
    assert rec1["wind_speed_kmh"] == 10.8
    assert rec1["rainfall_mm"] == 0.0
    assert rec1["observed_at"] == "2024-01-01T00:00:00Z"
    assert rec1["data_source"] == "NASA_POWER_DAILY"
    assert rec1["is_simulated"] is False
    assert rec1["source_metadata"]["time_standard"] == "UTC"
    assert rec1["source_metadata"]["api_version"] == "v2.test"
    assert rec1["source_metadata"]["parameters"]["WS10M"]["units"] == "m/s"
    assert validate_observation(rec1)["source_metadata"]["source_products"] == ["GEOSIT", "POWER"]

    # Second record checks
    rec2 = records[1]
    assert rec2["temperature_c"] == 16.0
    assert rec2["humidity_pct"] == 70.2
    assert rec2["wind_speed_kmh"] == 19.8  # 5.5 * 3.6 = 19.8
    assert rec2["rainfall_mm"] == 12.4
    assert rec2["observed_at"] == "2024-01-02T00:00:00Z"
    assert rec2["is_simulated"] is False

    # Ensure output passes strict schema validation in data_loader
    for r in records:
        validated = validate_observation(r)
        assert validated["is_simulated"] is False


def test_normalize_with_missing_and_fill_measurements():
    payload_with_fill = {
        "properties": {
            "parameter": {
                "T2M": {"20240101": -999.0},
                "RH2M": {"20240101": 50.0},
                "WS10M": {"20240101": -999.0},
                "PRECTOTCORR": {"20240101": None},
            }
        }
    }
    records = normalize_nasa_power_records(
        raw_payload=payload_with_fill,
        location_id="test-loc",
        location_name="Test Loc",
        latitude=10.0,
        longitude=20.0,
    )
    assert len(records) == 1
    rec = records[0]
    # Missing values must be None, never 0
    assert rec["temperature_c"] is None
    assert rec["humidity_pct"] == 50.0
    assert rec["wind_speed_kmh"] is None
    assert rec["rainfall_mm"] is None
    assert rec["is_simulated"] is False

    # Validated with data_loader
    validated = validate_observation(rec)
    assert validated["temperature_c"] is None
    assert validated["wind_speed_kmh"] is None


def test_normalizer_rejects_non_utc_payload():
    payload = dict(SAMPLE_RAW_NASA_POWER_RESPONSE)
    payload["header"] = {**payload["header"], "time_standard": "LST"}
    with pytest.raises(NasaPowerError, match="Expected NASA POWER UTC"):
        normalize_nasa_power_records(payload, "test", "Test", 0, 0)


def test_normalizer_rejects_malformed_payload_shapes():
    with pytest.raises(NasaPowerError, match="JSON object"):
        normalize_nasa_power_records([], "test", "Test", 0, 0)
    with pytest.raises(NasaPowerError, match="parameter data"):
        normalize_nasa_power_records({"properties": {"parameter": {}}}, "test", "Test", 0, 0)


def test_clean_measurement_rejects_non_finite_numbers():
    assert clean_measurement("nan") is None
    assert clean_measurement("inf") is None
    assert clean_measurement(float("-inf")) is None


def test_fetch_requests_utc_with_bounded_timeout(monkeypatch):
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"properties":{"parameter":{}}}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    fetch_nasa_power_point(30.0, 31.0, "20260101", "20260102", timeout=7)
    query = parse_qs(urlsplit(captured["request"].full_url).query)
    assert query["time-standard"] == ["UTC"]
    assert captured["timeout"] == 7


def test_provider_end_to_end_mocked(tmp_path):
    mock_fetch = MagicMock(return_value=SAMPLE_RAW_NASA_POWER_RESPONSE)
    test_locs = [
        {"location_id": "cairo-eg", "location_name": "Cairo, Egypt", "latitude": 30.0444, "longitude": 31.2357}
    ]

    raw_dir = tmp_path / "raw"
    proc_dir = tmp_path / "processed"

    provider = create_nasa_power_provider(
        locations=test_locs,
        start_date="20240101",
        end_date="20240102",
        raw_output_dir=raw_dir,
        processed_output_dir=proc_dir,
        fetch_func=mock_fetch,
    )

    result = get_observations(provider=provider)
    assert result["mode"] == "live"
    assert len(result["observations"]) == 2
    assert result["observations"][0]["is_simulated"] is False
    assert result["observations"][0]["data_source"] == "NASA_POWER_DAILY"

    # Verify persistence files created
    raw_files = list(raw_dir.glob("*.json"))
    proc_files = list(proc_dir.glob("*.json"))
    assert len(raw_files) == 1
    assert len(proc_files) == 1

    proc_json = json.loads(proc_files[0].read_text(encoding="utf-8"))
    assert proc_json["metadata"]["source"] == "NASA_POWER_DAILY"
    assert len(proc_json["observations"]) == 2


def test_provider_network_failure_falls_back_to_demo():
    def failing_fetch(*args, **kwargs):
        raise NasaPowerError("Simulated network timeout/HTTP 500 error")

    test_locs = [
        {"location_id": "cairo-eg", "location_name": "Cairo, Egypt", "latitude": 30.0444, "longitude": 31.2357}
    ]

    provider = create_nasa_power_provider(
        locations=test_locs,
        fetch_func=failing_fetch,
    )

    # get_observations catches provider failure and safely falls back to demo data
    result = get_observations(provider=provider)
    assert result["mode"] == "demo"
    assert len(result["observations"]) == 7  # demo observations count
    assert any("Live provider failed" in n for n in result["notes"])
    assert result["observations"][0]["is_simulated"] is True


def test_real_observations_pipeline_compatibility():
    """Verify real NASA POWER records flow cleanly through analysis and incident store."""
    records = normalize_nasa_power_records(
        raw_payload=SAMPLE_RAW_NASA_POWER_RESPONSE,
        location_id="cairo-eg",
        location_name="Cairo, Egypt",
        latitude=30.0444,
        longitude=31.2357,
    )
    assessments = assess_all(records)
    assert len(assessments) == 2
    for a in assessments:
        assert a["is_simulated"] is False
        assert a["status"] == "assessed"
        assert a["risk_level"] in config.RISK_LEVELS

    store = IncidentStore()
    store.register_alerts(assessments)
    # Calmer winter observations in sample -> Low risk, no active alerts/incidents
    assert len(store.list_incidents()) == 0
