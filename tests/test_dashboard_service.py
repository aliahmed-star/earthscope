from datetime import date

import pytest

import dashboard_service as svc


PARAMETER_METADATA = {
    "T2M": {"longname": "Temperature at 2 Meters", "units": "C"},
    "RH2M": {"longname": "Relative Humidity at 2 Meters", "units": "%"},
    "WS10M": {"longname": "Wind Speed at 10 Meters", "units": "m/s"},
    "PRECTOTCORR": {"longname": "Precipitation Corrected", "units": "mm/day"},
}


def _power_payload(days, start_value):
    values = {}
    for offset, day in enumerate(days):
        values[day] = start_value + offset
    return {
        "header": {
            "time_standard": "UTC",
            "community": "RE",
            "sources": ["POWER"],
            "api": {"name": "POWER Daily API", "version": "v2.test"},
        },
        "parameters": PARAMETER_METADATA,
        "properties": {
            "parameter": {
                "T2M": values,
                "RH2M": {day: 50 for day in days},
                "WS10M": {day: 5 for day in days},
                "PRECTOTCORR": {day: 1 for day in days},
            }
        },
    }


def test_live_series_aligns_missing_days_and_preserves_source_metadata(monkeypatch):
    monkeypatch.setattr(svc, "_cache", {})
    calls = []

    def fake_fetch(latitude, longitude, start_date, end_date):
        calls.append((latitude, longitude, start_date, end_date))
        if latitude == 30.0444:
            return _power_payload(["20260101", "20260103"], 20)
        if latitude == 33.4484:
            return _power_payload(["20260102", "20260103"], 22)
        raise AssertionError("Only the requested locations should be fetched")

    params = {
        "mode": "live",
        "station_ids": ["cairo-eg", "phoenix-us"],
        "start": date(2026, 1, 1),
        "end": date(2026, 1, 3),
        "fetch": fake_fetch,
    }
    first = svc.build_dashboard(**params)

    assert len(calls) == 2
    assert first["mode"] == "live"
    assert first["range"] == {"start": "2026-01-01", "end": "2026-01-03"}
    assert first["retrieved_at"].endswith("Z")
    assert first["source_metadata"]["api_version"] == "v2.test"
    assert first["source_metadata"]["time_standard"] == "UTC"
    assert first["source_metadata"]["parameters"]["PRECTOTCORR"]["units"] == "mm/day"

    dates = ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert first["series"]["cairo-eg"]["dates"] == dates
    assert first["series"]["cairo-eg"]["temperature"] == [20.0, None, 21.0]
    assert first["series"]["phoenix-us"]["dates"] == dates
    assert first["series"]["phoenix-us"]["temperature"] == [None, 22.0, 23.0]

    second = svc.build_dashboard(**params)
    assert len(calls) == 2
    assert second["retrieved_at"] == first["retrieved_at"]


def test_demo_selection_filters_locations():
    result = svc.build_dashboard(mode="demo", station_ids=["manila-ph"])
    assert [station["id"] for station in result["stations"]] == ["manila-ph"]
    assert set(result["series"]) == {"manila-ph"}
    assert result["is_simulated"] is True
    assert result["incidents"]


def test_live_failure_fallback_is_labelled_and_respects_selection(monkeypatch):
    monkeypatch.setattr(svc, "_cache", {})

    def failing_fetch(**kwargs):
        raise TimeoutError("upstream timeout")

    result = svc.build_dashboard(
        mode="live",
        station_ids=["manila-ph"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 2),
        fetch=failing_fetch,
    )
    assert result["mode"] == "demo"
    assert result["requested_mode"] == "live"
    assert result["is_simulated"] is True
    assert [station["id"] for station in result["stations"]] == ["manila-ph"]
    assert result["retrieved_at"] is None
    assert any("NASA POWER request failed" in note for note in result["notes"])


def test_live_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(svc, "_cache", {})
    monkeypatch.setattr(svc, "MAX_CACHE_ENTRIES", 2)

    def fake_fetch(latitude, longitude, start_date, end_date):
        return _power_payload([start_date], 20)

    for day in (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)):
        svc.build_dashboard(
            mode="live",
            station_ids=["cairo-eg"],
            start=day,
            end=day,
            fetch=fake_fetch,
        )
    assert len(svc._cache) == 2


def test_unknown_mode_and_location_are_rejected():
    with pytest.raises(ValueError, match="mode must be"):
        svc.build_dashboard(mode="other")
    with pytest.raises(ValueError, match="Unknown location"):
        svc.build_dashboard(mode="demo", station_ids=["not-a-location"])
