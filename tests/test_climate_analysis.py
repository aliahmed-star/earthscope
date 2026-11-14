from datetime import date, timedelta

import pytest

from earthscope.climate_analysis import compare_locations
from earthscope.history_store import HistoryStore


VARIABLES = {
    "T2M": ("°C", "°C"),
    "RH2M": ("%", "%"),
    "WS10M": ("km/h", "m/s"),
    "PRECTOTCORR": ("mm/day", "mm/day"),
}


def _insert_complete_decade(store, locations):
    rows = []
    for index, location in enumerate(locations):
        store.register_location(location)
        for year in range(2015, 2025):
            day = date(year, 1, 1)
            end = date(year, 12, 31)
            while day <= end:
                for code, (unit, raw_unit) in VARIABLES.items():
                    base = {
                        "T2M": 10.0 + index * 2.0 + (year - 2015) * (index + 1) * 0.5,
                        "RH2M": 40.0 + index,
                        "WS10M": 12.0 + index,
                        "PRECTOTCORR": 1.0 + index * 0.1,
                    }[code]
                    rows.append({
                        "location_id": location["location_id"], "variable_code": code,
                        "observed_on": day.isoformat(), "raw_value": base,
                        "raw_unit": raw_unit, "normalized_value": base,
                        "canonical_unit": unit, "source_metadata": {"fixture": "deterministic-test"},
                    })
                day += timedelta(days=1)
    store.upsert_observations(rows)


def _locations():
    return [
        {"location_id": "test-a", "location_name": "Test A", "latitude": 10.0, "longitude": 20.0,
         "country_name": "Testland A", "country_code": "TA"},
        {"location_id": "test-b", "location_name": "Test B", "latitude": -10.0, "longitude": 30.0,
         "country_name": "Testland B", "country_code": "TB"},
    ]


def test_complete_year_qualification_requires_every_daily_value_for_all_four_variables(tmp_path):
    store = HistoryStore(tmp_path / "coverage.sqlite3")
    locations = _locations()
    _insert_complete_decade(store, locations)
    coverage = {item["location_id"]: item for item in store.availability()["coverage"]}
    assert coverage["test-a"]["qualified_10_complete_years"] is True
    assert coverage["test-a"]["common_complete_years"] == list(range(2015, 2025))

    store.upsert_observations([{
        "location_id": "test-a", "variable_code": "T2M", "observed_on": "2017-02-03",
        "raw_value": None, "raw_unit": "°C", "normalized_value": None, "canonical_unit": "°C",
        "source_metadata": {"fixture": "missing-value-test"},
    }])
    degraded = next(item for item in store.availability()["coverage"] if item["location_id"] == "test-a")
    t2m = next(item for item in degraded["variables"] if item["variable_code"] == "T2M")
    assert t2m["missing_count"] == 1
    assert 2017 not in degraded["common_complete_years"]
    assert len(degraded["common_complete_years"]) == 9
    assert degraded["qualified_10_complete_years"] is False
    store.close()


def test_shared_range_reports_annual_seasonal_extrema_rankings_and_descriptive_trend(tmp_path):
    store = HistoryStore(tmp_path / "comparison.sqlite3")
    locations = _locations()
    _insert_complete_decade(store, locations)

    result = compare_locations(
        store, ["test-a", "test-b"], "2015-01-01", "2024-12-31", "T2M", min_locations=2,
    )
    assert result["range"] == {"start": "2015-01-01", "end": "2024-12-31"}
    assert result["ranked_location_ids"] == ["test-b", "test-a"]
    assert result["locations"][0]["annual_series"][0]["value"] == pytest.approx(10.0)
    assert result["locations"][1]["annual_series"][0]["value"] == pytest.approx(12.0)
    assert result["locations"][0]["complete_year_count"] == 10
    assert result["locations"][0]["trend"]["slope_per_year"] == pytest.approx(0.5)
    assert result["locations"][1]["trend"]["slope_per_year"] == pytest.approx(1.0)
    assert result["locations"][0]["minimum_daily"]["date"] == "2015-01-01"
    assert result["locations"][0]["maximum_daily"]["date"] == "2024-01-01"
    assert set(result["locations"][0]["seasonal_daily_means"]) == {"winter", "spring", "summer", "autumn"}
    assert result["locations"][1]["seasonal_daily_means"]["summer"]["mean_daily_value"] == pytest.approx(16.5, abs=0.01)
    assert result["insights"][0]["kind"] == "highest_average"
    assert any("not causal" in caveat for caveat in result["caveats"])
    store.close()


def test_trend_excludes_partial_year_edges_and_withholds_short_record():
    store = HistoryStore(":memory:")
    ids = []
    rows = []
    for index, location in enumerate(_locations()):
        store.register_location(location)
        ids.append(location["location_id"])
        for day, value in (("2020-06-01", 10.0 + index), ("2021-06-01", 11.0 + index)):
            rows.append({
                "location_id": location["location_id"], "variable_code": "T2M", "observed_on": day,
                "raw_value": value, "raw_unit": "°C", "normalized_value": value, "canonical_unit": "°C",
                "source_metadata": {"fixture": "partial-year-test"},
            })
    store.upsert_observations(rows)
    result = compare_locations(store, ids, "2020-03-01", "2021-10-31", "T2M", min_locations=2)
    for item in result["locations"]:
        assert item["trend"]["status"] == "insufficient_complete_years"
        assert item["trend"]["slope_per_year"] is None
        assert any("partial calendar years" in warning for warning in item["warnings"])
    store.close()
