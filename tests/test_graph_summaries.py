import json
from datetime import date, timedelta

import pytest

from earthscope.graph_summaries import summarize_dashboard_series


ENTRY_FIELDS = {
    "location_id", "location_name", "summary", "count", "missing_count", "coverage_pct",
    "min", "max", "mean", "median", "change", "trend_per_year", "trend_direction",
    "comparison", "monthly_means", "potential_outliers", "relationships", "caveats",
}


def make_series(location_id="loc-a", dates=None, **variables):
    dates = dates or ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
    item = {"dates": dates}
    item.update(variables)
    return {location_id: item}


def variable(result, location="loc-a", name="temperature"):
    entries = result["variables"][name]["locations"]
    return next(entry for entry in entries if entry["location_id"] == location)


def test_exact_statistics_dates_coverage_and_change():
    dates = ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"]
    result = summarize_dashboard_series(
        make_series(
            dates=dates,
            temperature=[2, 4, 6, 8],
            humidity=[20, 40, 60, 80],
            wind=[1, 3, 5, 7],
            rainfall=[0, 2, 0, 6],
        ),
        [{"id": "loc-a", "name": "Sample Station"}],
    )
    summary = variable(result)
    assert result["variables"]["temperature"]["unit"] == "°C"
    assert summary["location_name"] == "Sample Station"
    assert set(summary) == ENTRY_FIELDS
    assert summary["count"] == 4
    assert summary["missing_count"] == 0
    assert summary["coverage_pct"] == 100.0
    assert summary["min"] == {"date": "2026-03-01", "value": 2.0}
    assert summary["max"] == {"date": "2026-03-04", "value": 8.0}
    assert summary["mean"] == 5.0
    assert summary["median"] == 5.0
    assert summary["change"] == {
        "start": {"value": 2.0, "date": "2026-03-01"},
        "end": {"value": 8.0, "date": "2026-03-04"},
        "change": 6.0,
        "change_pct": 300.0,
    }
    assert result["selected_range"] == {"start": "2026-03-01", "end": "2026-03-04"}
    assert "4 valid" in summary["summary"]


def test_measurement_units_match_plotted_variables():
    result = summarize_dashboard_series(
        make_series(temperature=[1, 2, 3, 4], humidity=[1, 2, 3, 4],
                    wind=[1, 2, 3, 4], rainfall=[1, 2, 3, 4]),
        {},
    )
    expected = {"temperature": "°C", "humidity": "%", "wind": "km/h", "rainfall": "mm/day"}
    assert {name: detail["unit"] for name, detail in result["variables"].items()} == expected


@pytest.mark.parametrize(
    "values,label",
    [
        ([float(index) for index in range(40)], "up"),
        ([float(40 - index) for index in range(40)], "down"),
        ([5.0] * 40, "stable"),
    ],
)
def test_trend_and_half_comparison_directions(values, label):
    dates = [(date(2026, 1, 1) + timedelta(days=index)).isoformat() for index in range(40)]
    result = summarize_dashboard_series(make_series(dates=dates, temperature=values), {})
    summary = variable(result)
    assert summary["trend_direction"] == label
    assert summary["trend_per_year"] == pytest.approx(
        (1 if label == "up" else -1 if label == "down" else 0) * 365.2425
    )
    assert summary["comparison"]["status"] == "computed"
    assert summary["comparison"]["label"] == label
    assert summary["comparison"]["first_half"]["count"] == 20
    assert summary["comparison"]["second_half"]["count"] == 20


def test_missing_blank_invalid_and_nonfinite_points_are_omitted_not_zero():
    dates = [f"2026-02-{day:02d}" for day in range(1, 8)]
    result = summarize_dashboard_series(
        make_series(dates=dates, temperature=[1, None, "", float("nan"), float("inf"), "bad", 7]),
        {},
    )
    summary = variable(result)
    assert summary["count"] == 2
    assert summary["missing_count"] == 5
    assert summary["coverage_pct"] == pytest.approx(200 / 7)
    assert summary["mean"] == 4.0
    assert summary["min"] == {"date": "2026-02-01", "value": 1.0}
    assert summary["max"] == {"date": "2026-02-07", "value": 7.0}
    assert any("missing values were omitted, not treated as zero" in note for note in summary["caveats"])


def test_empty_and_short_ranges_have_explicit_insufficiency_caveats():
    empty = summarize_dashboard_series({"loc-a": {"dates": [], "temperature": []}}, {})
    summary = variable(empty)
    assert summary["count"] == summary["missing_count"] == 0
    assert summary["mean"] is None
    assert summary["trend_per_year"] is None
    assert summary["potential_outliers"]["status"] == "insufficient_data"
    assert summary["monthly_means"]["seasonal_statement"] is None
    assert any("No valid values" in note for note in summary["caveats"])

    dates = [(date(2026, 1, 1) + timedelta(days=index)).isoformat() for index in range(29)]
    short = summarize_dashboard_series(
        make_series(dates=dates, temperature=list(range(29)), humidity=list(range(29))), {},
    )
    short_summary = variable(short)
    assert short_summary["trend_per_year"] is None
    assert short_summary["trend_direction"] is None
    assert short_summary["comparison"]["status"] == "insufficient_data"
    assert short_summary["potential_outliers"]["status"] == "insufficient_data"
    assert short_summary["relationships"][0]["status"] == "insufficient_pairwise_data"
    assert short_summary["relationships"][0]["n"] == 29
    assert any("at least 30" in note for note in short_summary["caveats"])


def test_half_comparison_requires_ten_points_in_each_half():
    dates = [(date(2026, 1, 1) + timedelta(days=index)).isoformat() for index in range(41)]
    # 30 valid observations overall, but only nine in the first time half.
    values = [1] * 9 + [None] * 11 + list(range(21))
    result = summarize_dashboard_series(make_series(dates=dates, temperature=values), {})
    summary = variable(result)
    assert summary["count"] == 30
    assert summary["trend_per_year"] is not None
    assert summary["comparison"]["status"] == "insufficient_data"
    assert any("at least 10 valid points in each half" in note for note in summary["caveats"])


def test_seasonal_means_are_withheld_until_two_years_and_365_values():
    short_dates = [(date(2025, 1, 1) + timedelta(days=index)).isoformat() for index in range(365)]
    short = summarize_dashboard_series(make_series(dates=short_dates, temperature=list(range(365))), {})
    summary = variable(short)
    assert summary["monthly_means"]["status"] == "insufficient_data"
    assert summary["monthly_means"]["months"] == []
    assert summary["monthly_means"]["seasonal_statement"] is None
    assert any("at least 365 valid values spanning at least two calendar years" in note
               for note in summary["caveats"])

    long_dates = [(date(2020, 1, 1) + timedelta(days=index)).isoformat() for index in range(732)]
    values = [float(date.fromisoformat(day).month) for day in long_dates]
    long_result = summarize_dashboard_series(make_series(dates=long_dates, temperature=values), {})
    long_summary = variable(long_result)
    assert long_summary["monthly_means"]["status"] == "computed"
    assert len(long_summary["monthly_means"]["months"]) == 12
    january = next(item for item in long_summary["monthly_means"]["months"] if item["month"] == 1)
    assert january["mean"] == 1.0
    assert "December is highest" in long_summary["monthly_means"]["seasonal_statement"]
    assert "January lowest" in long_summary["monthly_means"]["seasonal_statement"]


def test_outlier_screen_is_labeled_and_examples_are_capped_at_three():
    dates = [(date(2026, 1, 1) + timedelta(days=index)).isoformat() for index in range(40)]
    values = [0.0] * 35 + [100.0] * 5
    summary = variable(summarize_dashboard_series(make_series(dates=dates, temperature=values), {}))
    assert summary["potential_outliers"]["status"] == "screened"
    assert summary["potential_outliers"]["count"] == 5
    assert len(summary["potential_outliers"]["examples"]) == 3
    assert summary["potential_outliers"]["label"] == "statistical screen, not an event"


def test_correlations_are_pairwise_only_descriptive_and_skip_unplotted_variables():
    dates = [(date(2026, 1, 1) + timedelta(days=index)).isoformat() for index in range(40)]
    temperatures = [float(index) for index in range(40)]
    humidities = [3.0 * value + 10 for value in temperatures]
    result = summarize_dashboard_series(
        make_series(dates=dates, temperature=temperatures, humidity=humidities, wind=[2.0] * 40), {},
    )
    relationships = {item["variable"]: item for item in variable(result)["relationships"]}
    assert set(relationships) == {"humidity", "wind"}
    assert relationships["humidity"]["status"] == "computed"
    assert relationships["humidity"]["n"] == 40
    assert relationships["humidity"]["coefficient"] == pytest.approx(1.0)
    assert relationships["humidity"]["interpretation"] == "descriptive association, not causal"
    assert relationships["wind"]["status"] == "zero_variance"
    assert relationships["wind"]["n"] == 40
    assert variable(result, name="rainfall")["relationships"] == []


def test_selection_and_date_filter_are_applied_to_each_call_without_stale_results():
    dates = [f"2026-04-{day:02d}" for day in range(1, 5)]
    selected = {
        "loc-a": {"dates": dates, "temperature": [1, 2, 3, 4]},
        "loc-b": {"dates": dates, "temperature": [10, 20, 30, 40]},
    }
    first = summarize_dashboard_series(selected, {"loc-a": {"name": "A"}, "loc-b": {"name": "B"}})
    assert {entry["location_id"] for entry in first["variables"]["temperature"]["locations"]} == {"loc-a", "loc-b"}
    assert variable(first, "loc-a")["mean"] == 2.5
    assert variable(first, "loc-b")["mean"] == 25.0

    changed = summarize_dashboard_series(
        {"loc-b": selected["loc-b"]}, {"loc-b": {"name": "B"}},
        start_date="2026-04-02", end_date="2026-04-03",
    )
    assert [entry["location_id"] for entry in changed["variables"]["temperature"]["locations"]] == ["loc-b"]
    assert variable(changed, "loc-b")["count"] == 2
    assert variable(changed, "loc-b")["mean"] == 25.0
    assert changed["selected_range"] == {"start": "2026-04-02", "end": "2026-04-03"}


def test_zero_start_value_has_json_safe_undefined_percent_change_and_nonfinite_never_leaks():
    dates = [(date(2026, 1, 1) + timedelta(days=index)).isoformat() for index in range(30)]
    result = summarize_dashboard_series(
        make_series(dates=dates, temperature=[0] + [float(index) for index in range(1, 30)]), {},
    )
    summary = variable(result)
    assert summary["change"]["change"] == 29.0
    assert summary["change"]["change_pct"] is None
    encoded = json.dumps(result, allow_nan=False)
    assert "NaN" not in encoded and "Infinity" not in encoded


def test_invalid_date_order_is_rejected():
    with pytest.raises(ValueError, match="on or before"):
        summarize_dashboard_series({}, {}, start_date="2026-02-02", end_date="2026-02-01")
