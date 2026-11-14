"""Comparable annual, seasonal, and descriptive trend statistics from SQLite rows."""
from __future__ import annotations

import calendar
import math
from datetime import date
from typing import Any, Mapping, Sequence


VARIABLES: dict[str, dict[str, str]] = {
    "T2M": {"label": "Air temperature", "unit": "°C", "annual_aggregation": "mean"},
    "RH2M": {"label": "Relative humidity", "unit": "%", "annual_aggregation": "mean"},
    "WS10M": {"label": "Wind speed", "unit": "km/h", "annual_aggregation": "mean"},
    "PRECTOTCORR": {"label": "Precipitation", "unit": "mm/day", "annual_aggregation": "sum"},
}
MIN_TREND_YEARS = 10


def _as_date(value: str | date, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO calendar date") from exc


def _ols_slope(years: Sequence[int], values: Sequence[float]) -> float | None:
    if len(years) != len(values) or len(years) < 2:
        return None
    xbar = sum(years) / len(years)
    ybar = sum(values) / len(values)
    denom = sum((year - xbar) ** 2 for year in years)
    if not denom:
        return None
    return sum((year - xbar) * (value - ybar) for year, value in zip(years, values)) / denom


def _season_months(latitude: float) -> dict[str, set[int]]:
    # Consistent meteorological seasons; southern labels are shifted by six months.
    if latitude < 0:
        return {"summer": {12, 1, 2}, "autumn": {3, 4, 5}, "winter": {6, 7, 8}, "spring": {9, 10, 11}}
    return {"winter": {12, 1, 2}, "spring": {3, 4, 5}, "summer": {6, 7, 8}, "autumn": {9, 10, 11}}


def compare_locations(
    store: Any,
    location_ids: Sequence[str],
    start_date: str | date,
    end_date: str | date,
    variable: str = "T2M",
    min_locations: int = 2,
) -> dict[str, Any]:
    """Compare two or more selected point locations over one shared inclusive UTC window."""
    start, end = _as_date(start_date, "start_date"), _as_date(end_date, "end_date")
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    if (end - start).days + 1 > 50 * 366:
        raise ValueError("Comparison windows are limited to 50 years")
    code = str(variable).upper()
    if code not in VARIABLES:
        raise ValueError(f"variable must be one of {', '.join(VARIABLES)}")
    ids = list(dict.fromkeys(str(item) for item in location_ids))
    if len(ids) < min_locations:
        raise ValueError(f"Select at least {min_locations} location(s)")
    if len(ids) > 15:
        raise ValueError("Select no more than 15 locations for one comparison")

    marks = ",".join("?" for _ in ids)
    metadata_rows = store._connection.execute(
        f"SELECT location_id, location_name, country_name, country_code, latitude, longitude "
        f"FROM locations WHERE location_id IN ({marks}) ORDER BY location_id", ids
    ).fetchall()
    metadata = {row["location_id"]: dict(row) for row in metadata_rows}
    unknown = [item for item in ids if item not in metadata]
    if unknown:
        raise ValueError("Unknown location ID(s): " + ", ".join(unknown))

    spec = VARIABLES[code]
    unit = spec["unit"]
    expected_total = (end - start).days + 1
    results: list[dict[str, Any]] = []
    full_year_values: dict[str, dict[int, float]] = {}

    for location_id in ids:
        loc = metadata[location_id]
        query = store.query_observations(location_id, code, start.isoformat(), end.isoformat(), limit=50000)
        dated: dict[date, float | None] = {}
        for row in query["rows"]:
            try:
                day = date.fromisoformat(row["observed_on"])
            except (TypeError, ValueError):
                continue
            value = row.get("value")
            try:
                value = float(value) if value is not None and math.isfinite(float(value)) else None
            except (TypeError, ValueError, OverflowError):
                value = None
            dated[day] = value
        valid = [(day, value) for day, value in dated.items() if value is not None]
        valid.sort(key=lambda pair: pair[0])
        valid_values = [value for _day, value in valid]
        valid_count = len(valid)
        annual = []
        complete_values: dict[int, float] = {}
        for year in range(start.year, end.year + 1):
            year_start = max(start, date(year, 1, 1))
            year_end = min(end, date(year, 12, 31))
            expected_days = (year_end - year_start).days + 1
            values = [value for day, value in valid if year_start <= day <= year_end]
            full_calendar_window = year_start == date(year, 1, 1) and year_end == date(year, 12, 31)
            is_complete = full_calendar_window and len(values) == (366 if calendar.isleap(year) else 365)
            annual_value = (sum(values) if code == "PRECTOTCORR" else sum(values) / len(values)) if values else None
            annual.append({
                "year": year, "value": annual_value, "unit": "mm/year" if code == "PRECTOTCORR" else unit,
                "valid_days": len(values), "expected_days": expected_days,
                "completeness_pct": round(100.0 * len(values) / expected_days, 3) if expected_days else None,
                "complete_calendar_year": is_complete,
            })
            if is_complete and annual_value is not None:
                complete_values[year] = annual_value

        seasonal_months = _season_months(float(loc["latitude"]))
        seasonal = {}
        for season, months in seasonal_months.items():
            vals = [value for day, value in valid if day.month in months]
            seasonal[season] = {
                "months": sorted(months), "valid_days": len(vals),
                "mean_daily_value": sum(vals) / len(vals) if vals else None,
                "unit": unit,
            }
        years = sorted(complete_values)
        trend = _ols_slope(years, [complete_values[y] for y in years]) if len(years) >= MIN_TREND_YEARS else None
        if trend is None:
            trend_result = {
                "status": "insufficient_complete_years", "slope_per_year": None,
                "slope_per_decade": None, "complete_year_count": len(years),
                "method": "ordinary least squares fitted to complete calendar-year aggregates",
                "interpretation": "descriptive, not causal; no statistical-significance claim",
            }
        else:
            trend_result = {
                "status": "computed", "slope_per_year": trend,
                "slope_per_decade": trend * 10, "complete_year_count": len(years),
                "method": "ordinary least squares fitted to complete calendar-year aggregates",
                "interpretation": "descriptive, not causal; no statistical-significance claim",
            }
        changes = [
            {"from_year": y0, "to_year": y1, "change": complete_values[y1] - complete_values[y0], "unit": "mm/year" if code == "PRECTOTCORR" else unit}
            for y0, y1 in zip(years, years[1:]) if y1 == y0 + 1
        ]
        largest_change = max(changes, key=lambda item: abs(item["change"])) if changes else None
        min_record = min(valid, key=lambda item: item[1]) if valid else None
        max_record = max(valid, key=lambda item: item[1]) if valid else None
        period_total = sum(valid_values) if code == "PRECTOTCORR" else None
        annual_avg = (sum(complete_values.values()) / len(complete_values)) if complete_values else None
        average_daily = (sum(valid_values) / valid_count) if valid_count else None
        ranking_value = annual_avg if code == "PRECTOTCORR" else average_daily
        record_count = len(dated)
        missing_days = max(0, expected_total - valid_count)
        warnings = []
        if missing_days:
            warnings.append(f"{missing_days} of {expected_total} requested days lack a usable value; none were filled.")
        if len(years) < MIN_TREND_YEARS:
            warnings.append(f"Only {len(years)} complete calendar years are available in this selection; trend rate requires {MIN_TREND_YEARS}.")
        if start != date(start.year, 1, 1) or end != date(end.year, 12, 31):
            warnings.append("Trend fitting excludes partial calendar years at the selected range edges.")
        results.append({
            "location_id": location_id, "location_name": loc["location_name"],
            "country_name": loc["country_name"], "country_code": loc["country_code"],
            "latitude": loc["latitude"], "longitude": loc["longitude"],
            "requested_days": expected_total, "recorded_days": record_count,
            "valid_days": valid_count, "missing_days": missing_days,
            "completeness_pct": round(100.0 * valid_count / expected_total, 3) if expected_total else None,
            "coverage_start": min(dated).isoformat() if dated else None,
            "coverage_end": max(dated).isoformat() if dated else None,
            "mean_daily_value": average_daily, "mean_daily_unit": unit,
            "period_precipitation_total_mm": period_total,
            "mean_complete_year_value": annual_avg,
            "ranking_value": ranking_value,
            "ranking_metric": "mean annual precipitation total" if code == "PRECTOTCORR" else "mean daily value",
            "minimum_daily": {"date": min_record[0].isoformat(), "value": min_record[1]} if min_record else None,
            "maximum_daily": {"date": max_record[0].isoformat(), "value": max_record[1]} if max_record else None,
            "annual_series": annual, "complete_year_values": complete_values,
            "complete_year_count": len(years), "trend": trend_result,
            "largest_consecutive_year_change": largest_change,
            "seasonal_daily_means": seasonal, "warnings": warnings,
        })
        full_year_values[location_id] = complete_values

    ranking = sorted(
        (item for item in results if item["ranking_value"] is not None),
        key=lambda item: item["ranking_value"], reverse=True,
    )
    trend_rank = sorted(
        (item for item in results if item["trend"]["slope_per_decade"] is not None),
        key=lambda item: abs(item["trend"]["slope_per_decade"]), reverse=True,
    )
    highest_record = max(
        (item for item in results if item["maximum_daily"]),
        key=lambda item: item["maximum_daily"]["value"], default=None,
    )
    insights = []
    if ranking:
        insights.append({"kind": "highest_average", "location_id": ranking[0]["location_id"],
                         "value": ranking[0]["ranking_value"], "metric": ranking[0]["ranking_metric"]})
    if highest_record:
        insights.append({"kind": "highest_daily_maximum", "location_id": highest_record["location_id"],
                         "value": highest_record["maximum_daily"]["value"],
                         "date": highest_record["maximum_daily"]["date"], "metric": "maximum daily value"})
    if trend_rank:
        item = trend_rank[0]
        insights.append({"kind": "largest_absolute_trend", "location_id": item["location_id"],
                         "value": item["trend"]["slope_per_decade"], "metric": f"OLS change per decade ({unit})"})
    for item in results:
        item.pop("complete_year_values", None)
    return {
        "variable": code, "label": spec["label"], "unit": unit,
        "annual_aggregation": spec["annual_aggregation"],
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "locations": results,
        "ranked_location_ids": [item["location_id"] for item in ranking],
        "trend_ranked_location_ids": [item["location_id"] for item in trend_rank],
        "insights": insights,
        "caveats": [
            "Each record is a NASA POWER daily gridded estimate at the listed city coordinates, not a country-wide average or in-situ station observation.",
            "Annual trends use only complete calendar years and are ordinary least-squares descriptions, not causal claims or statistical-significance tests.",
            "Precipitation values are daily amounts; annual rainfall is the sum of valid daily values, without filling missing days.",
            "Meteorological seasons are assigned by hemisphere from calendar months; this is not a locally calibrated wet/dry-season classification.",
        ],
    }
