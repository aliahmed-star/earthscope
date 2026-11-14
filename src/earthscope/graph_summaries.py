"""Deterministic statistical summaries for the values plotted on the dashboard.

This module has no I/O or model dependencies. Missing or non-finite values are
omitted from calculations and never interpreted as zero. All narrative text is
derived only from the supplied series and station metadata.
"""

from calendar import month_name
from datetime import date, datetime
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


_VARIABLE_UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "wind": "km/h",
    "rainfall": "mm/day",
}
_MIN_TREND_POINTS = 30
_MIN_HALF_POINTS = 10
_MIN_SEASONAL_POINTS = 365
_DAYS_PER_YEAR = 365.2425


def _as_date(value: Any, label: str = "date") -> date:
    """Parse date-like dashboard values without relying on the current clock."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            # Dashboard series use YYYY-MM-DD. Also accept ISO timestamps by
            # taking their date portion; the chart itself is date-granular.
            return date.fromisoformat(value[:10])
        except (TypeError, ValueError):
            pass
    raise ValueError(f"{label} must be a date, datetime, or ISO date string; got {value!r}.")


def _date_text(value: date) -> str:
    return value.isoformat()


def _two_year_anniversary(day: date) -> date:
    """Return the calendar date two years later, clamping leap day if needed."""
    year = day.year + 2
    month = day.month
    last_day = (date(year + (month == 12), 1 if month == 12 else month + 1, 1)
                - date.resolution).day
    return date(year, month, min(day.day, last_day))


def _finite_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _interpolated_quantile(sorted_values: Sequence[float], probability: float) -> float:
    """Linear-interpolated quantile (the common (n - 1) * p definition)."""
    position = (len(sorted_values) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])


def _clean_zero(value: float) -> float:
    return 0.0 if value == 0 else float(value)


def _direction(delta: float, scale: float) -> str:
    """Classify a numerical change, treating floating-point noise as stable."""
    tolerance = max(1.0, abs(scale)) * 1e-12
    if abs(delta) <= tolerance:
        return "stable"
    return "up" if delta > 0 else "down"


def _station_for(stations: Any, location_id: Any) -> Mapping[str, Any]:
    if isinstance(stations, Mapping):
        candidate = stations.get(location_id)
        if candidate is None:
            candidate = stations.get(str(location_id))
        return candidate if isinstance(candidate, Mapping) else {}
    if isinstance(stations, (list, tuple)):
        for candidate in stations:
            if not isinstance(candidate, Mapping):
                continue
            candidate_id = candidate.get("id", candidate.get("location_id"))
            if candidate_id == location_id or str(candidate_id) == str(location_id):
                return candidate
    return {}


def _pearson(pairs: Sequence[Tuple[float, float]]) -> Optional[float]:
    if len(pairs) < 2:
        return None
    x_mean = sum(x for x, _ in pairs) / len(pairs)
    y_mean = sum(y for _, y in pairs) / len(pairs)
    x_dev = [x - x_mean for x, _ in pairs]
    y_dev = [y - y_mean for _, y in pairs]
    x_ss = sum(value * value for value in x_dev)
    y_ss = sum(value * value for value in y_dev)
    if x_ss == 0 or y_ss == 0:
        return None
    covariance = sum(x * y for x, y in zip(x_dev, y_dev))
    return max(-1.0, min(1.0, covariance / math.sqrt(x_ss * y_ss)))


def _correlation_summaries(
    variable: str,
    plotted_variables: Sequence[str],
    values_by_variable: Mapping[str, Sequence[Optional[float]]],
) -> List[Dict[str, Any]]:
    summaries = []
    for other in plotted_variables:
        if other == variable:
            continue
        pairs = [
            (left, right)
            for left, right in zip(values_by_variable[variable], values_by_variable[other])
            if left is not None and right is not None
        ]
        n = len(pairs)
        summary: Dict[str, Any] = {
            "variable": other,
            "unit": _VARIABLE_UNITS[other],
            "n": n,
            "coefficient": None,
            "status": "insufficient_pairwise_data",
            "interpretation": "descriptive association, not causal",
        }
        if n >= _MIN_TREND_POINTS:
            coefficient = _pearson(pairs)
            if coefficient is None:
                summary["status"] = "zero_variance"
            else:
                summary["status"] = "computed"
                summary["coefficient"] = _clean_zero(coefficient)
        summaries.append(summary)
    return summaries


def _variable_summary(
    variable: str,
    dates: Sequence[date],
    total: int,
    plotted: bool,
    values: Sequence[Optional[float]],
    values_by_variable: Mapping[str, Sequence[Optional[float]]],
    plotted_variables: Sequence[str],
) -> Dict[str, Any]:
    unit = _VARIABLE_UNITS[variable]
    valid = [(index, dates[index], value) for index, value in enumerate(values) if value is not None]
    n = len(valid)
    missing = total - n
    coverage = (100.0 * n / total) if total else None
    numeric = [record[2] for record in valid]

    result: Dict[str, Any] = {
        "unit": unit,
        "plotted": bool(plotted),
        "count": n,
        "missing": missing,
        "total": total,
        "coverage_pct": _clean_zero(coverage) if coverage is not None else None,
        "min": None,
        "max": None,
        "mean": None,
        "median": None,
        "start_end_change": None,
        "trend": {
            "status": "insufficient_data",
            "label": None,
            "slope_per_year": None,
            "n": n,
            "method": "ordinary least-squares fit against elapsed calendar days",
            "statement": None,
        },
        "half_comparison": {
            "status": "insufficient_data",
            "first_half": None,
            "second_half": None,
            "change_second_minus_first": None,
            "label": None,
        },
        "monthly_means": {"status": "insufficient_data", "months": []},
        "seasonal_statement": None,
        "outliers": {
            "status": "insufficient_data",
            "method": "1.5-IQR statistical screen, not an event",
            "label": "statistical screen, not an event",
            "lower_fence": None,
            "upper_fence": None,
            "count": 0,
            "examples": [],
        },
        "correlations": _correlation_summaries(variable, plotted_variables, values_by_variable)
        if plotted else [],
        "overview": "",
        "caveats": [],
    }

    if missing:
        result["caveats"].append(
            f"{missing} of {total} plotted date(s) have no usable {variable} value; "
            "missing values were omitted, not treated as zero."
        )
    if not plotted:
        result["caveats"].append(
            f"{variable} is absent from this location's plotted series; no values were inferred."
        )
    if n == 0:
        result["caveats"].append("No valid values are available; numerical statistics cannot be computed.")
        result["overview"] = f"No valid {variable} measurements are available ({unit})."
    else:
        mean = sum(numeric) / n
        median_values = sorted(numeric)
        if n % 2:
            median = median_values[n // 2]
        else:
            median = (median_values[n // 2 - 1] + median_values[n // 2]) / 2
        min_record = min(valid, key=lambda record: record[2])
        max_record = max(valid, key=lambda record: record[2])
        result.update({
            "min": {"value": min_record[2], "date": _date_text(min_record[1])},
            "max": {"value": max_record[2], "date": _date_text(max_record[1])},
            "mean": _clean_zero(mean),
            "median": _clean_zero(median),
        })
        first_record, last_record = valid[0], valid[-1]
        change = last_record[2] - first_record[2]
        percentage_change = (
            (100.0 * change / abs(first_record[2])) if first_record[2] != 0 else None
        )
        result["start_end_change"] = {
            "start": {"value": first_record[2], "date": _date_text(first_record[1])},
            "end": {"value": last_record[2], "date": _date_text(last_record[1])},
            "change": _clean_zero(change),
            "change_pct": _clean_zero(percentage_change) if percentage_change is not None else None,
        }
        result["overview"] = (
            f"{n} valid of {total} plotted {variable} date(s) "
            f"({coverage:.1f}% coverage); mean {mean:g} {unit}."
        )

    if n < _MIN_TREND_POINTS:
        result["caveats"].append(
            f"Only {n} valid {variable} point(s); slope/year, half comparison, outlier screen, "
            f"and correlations require at least {_MIN_TREND_POINTS} applicable points."
        )
    else:
        # The aligned dashboard axis is chronological. A duplicate date remains
        # a separate plotted observation, matching the underlying chart.
        day_offsets = [(record[1] - valid[0][1]).days for record in valid]
        x_mean = sum(day_offsets) / n
        y_mean = sum(numeric) / n
        denominator = sum((x - x_mean) ** 2 for x in day_offsets)
        if denominator == 0:
            result["trend"].update({"status": "zero_time_variance"})
            result["caveats"].append("Slope/year is unavailable because all valid points share one date.")
        else:
            daily_slope = sum((x - x_mean) * (y - y_mean)
                              for x, y in zip(day_offsets, numeric)) / denominator
            annual_slope = daily_slope * _DAYS_PER_YEAR
            label = _direction(annual_slope, max(numeric) - min(numeric))
            direction_text = {"up": "upward", "down": "downward", "stable": "approximately flat"}[label]
            result["trend"].update({
                "status": "computed",
                "label": label,
                "slope_per_year": _clean_zero(annual_slope),
                "statement": f"The fitted linear slope is {direction_text} ({annual_slope:g} {unit}/year); descriptive, not causal.",
            })

        midpoint = total // 2
        first_half = [record for record in valid if record[0] < midpoint]
        second_half = [record for record in valid if record[0] >= midpoint]
        if len(first_half) >= _MIN_HALF_POINTS and len(second_half) >= _MIN_HALF_POINTS:
            first_mean = sum(record[2] for record in first_half) / len(first_half)
            second_mean = sum(record[2] for record in second_half) / len(second_half)
            half_change = second_mean - first_mean
            half_label = _direction(half_change, max(numeric) - min(numeric))
            result["half_comparison"] = {
                "status": "computed",
                "first_half": {
                    "count": len(first_half), "mean": _clean_zero(first_mean),
                    "start_date": _date_text(first_half[0][1]),
                    "end_date": _date_text(first_half[-1][1]),
                },
                "second_half": {
                    "count": len(second_half), "mean": _clean_zero(second_mean),
                    "start_date": _date_text(second_half[0][1]),
                    "end_date": _date_text(second_half[-1][1]),
                },
                "change_second_minus_first": _clean_zero(half_change),
                "label": half_label,
            }
        else:
            result["caveats"].append(
                "Half comparison requires at least 10 valid points in each half of the selected date axis."
            )

        sorted_values = sorted(numeric)
        q1 = _interpolated_quantile(sorted_values, 0.25)
        q3 = _interpolated_quantile(sorted_values, 0.75)
        iqr = q3 - q1
        lower_fence = q1 - 1.5 * iqr
        upper_fence = q3 + 1.5 * iqr
        outlier_records = [record for record in valid
                           if record[2] < lower_fence or record[2] > upper_fence]
        result["outliers"] = {
            "status": "screened",
            "method": "1.5-IQR statistical screen, not an event",
            "label": "statistical screen, not an event",
            "lower_fence": _clean_zero(lower_fence),
            "upper_fence": _clean_zero(upper_fence),
            "count": len(outlier_records),
            "examples": [
                {"date": _date_text(record[1]), "value": record[2]}
                for record in outlier_records[:3]
            ],
        }

    seasonal_dates = [record[1] for record in valid]
    if n >= _MIN_SEASONAL_POINTS and seasonal_dates and (
        max(seasonal_dates) >= _two_year_anniversary(min(seasonal_dates))
    ):
        per_month: Dict[int, List[float]] = {}
        for _, day, value in valid:
            per_month.setdefault(day.month, []).append(value)
        monthly = [
            {"month": month, "month_name": month_name[month],
             "count": len(per_month[month]), "mean": _clean_zero(sum(per_month[month]) / len(per_month[month]))}
            for month in sorted(per_month)
        ]
        result["monthly_means"] = {"status": "computed", "months": monthly}
        if len(monthly) >= 2:
            lowest = min(monthly, key=lambda item: (item["mean"], item["month"]))
            highest = max(monthly, key=lambda item: (item["mean"], -item["month"]))
            if lowest["month"] == highest["month"]:
                result["seasonal_statement"] = (
                    f"Observed month-of-year means are equal at {lowest['mean']:g} {unit}; "
                    "this is a descriptive comparison, not evidence of a causal seasonal effect."
                )
            else:
                result["seasonal_statement"] = (
                    f"Among represented month-of-year means, {highest['month_name']} is highest "
                    f"({highest['mean']:g} {unit}) and {lowest['month_name']} lowest "
                    f"({lowest['mean']:g} {unit}); descriptive only, not causal."
                )
        else:
            result["seasonal_statement"] = (
                "Seasonal comparison is unavailable because valid data cover only one calendar month; "
                "no month-to-month pattern is inferred."
            )
    else:
        span_text = "no dated valid values"
        if seasonal_dates:
            span_days = (max(seasonal_dates) - min(seasonal_dates)).days
            span_text = f"a {span_days}-day span"
        result["caveats"].append(
            "Month-of-year means and a seasonal statement require at least 365 valid values "
            f"spanning at least two calendar years; got {n} values over {span_text}."
        )

    if not result["correlations"] and plotted:
        result["caveats"].append("No other plotted variables are available for pairwise correlation.")
    for correlation in result["correlations"]:
        if correlation["status"] == "insufficient_pairwise_data":
            result["caveats"].append(
                f"Correlation with {correlation['variable']} is omitted: only {correlation['n']} "
                "pairwise valid points; at least 30 are required."
            )
        elif correlation["status"] == "zero_variance":
            result["caveats"].append(
                f"Correlation with {correlation['variable']} is unavailable because at least one "
                "paired series has zero variance."
            )

    return result


def summarize_dashboard_series(
    series: Mapping[Any, Mapping[str, Any]],
    stations: Any,
    start_date: Any = None,
    end_date: Any = None,
) -> Dict[str, Any]:
    """Summarize each selected location and each dashboard variable.

    Args:
        series: Already-aligned ``{location_id: {dates, temperature, humidity,
            wind, rainfall}}`` plotted data. Each variable's array is aligned
            by index to ``dates``; absent, blank, non-numeric, NaN, and infinite
            values are considered missing.
        stations: Station metadata as a mapping keyed by id or a sequence of
            dictionaries containing ``id``/``location_id`` and optionally
            ``name``.
        start_date, end_date: Optional inclusive date filters (date, datetime,
            or ISO date strings).

    Returns a JSON-serializable mapping with a global overview and a
    variable-first ``variables`` mapping. Each variable contains its unit and
    one frontend-ready location entry for each selected location. Correlations
    use only keys actually plotted for a location, with at least 30 pairwise
    complete observations and non-zero variance in both variables.
    """
    requested_start = _as_date(start_date, "start_date") if start_date is not None else None
    requested_end = _as_date(end_date, "end_date") if end_date is not None else None
    if requested_start is not None and requested_end is not None and requested_start > requested_end:
        raise ValueError("start_date must be on or before end_date.")

    locations: Dict[str, Any] = {}
    all_selected_dates: List[date] = []
    for raw_location_id, location_series in series.items():
        location_id = str(raw_location_id)
        if not isinstance(location_series, Mapping):
            location_series = {}
        raw_dates = location_series.get("dates", [])
        if not isinstance(raw_dates, (list, tuple)):
            raw_dates = []
        parsed_dates = [_as_date(day, f"dates[{index}] for {location_id}")
                        for index, day in enumerate(raw_dates)]
        selected_indices = [
            index for index, day in enumerate(parsed_dates)
            if (requested_start is None or day >= requested_start)
            and (requested_end is None or day <= requested_end)
        ]
        # The dashboard aligns dates in chronological order; sorting indices
        # also makes outputs deterministic for equivalent unsorted inputs.
        selected_indices.sort(key=lambda index: (parsed_dates[index], index))
        selected_dates = [parsed_dates[index] for index in selected_indices]
        all_selected_dates.extend(selected_dates)
        plotted_variables = [name for name in _VARIABLE_UNITS if name in location_series]

        values_by_variable: Dict[str, List[Optional[float]]] = {}
        for variable in _VARIABLE_UNITS:
            raw_values = location_series.get(variable, [])
            if not isinstance(raw_values, (list, tuple)):
                raw_values = []
            values_by_variable[variable] = [
                _finite_number(raw_values[index]) if index < len(raw_values) else None
                for index in selected_indices
            ]

        variable_summaries = {
            variable: _variable_summary(
                variable=variable,
                dates=selected_dates,
                total=len(selected_dates),
                plotted=variable in plotted_variables,
                values=values_by_variable[variable],
                values_by_variable=values_by_variable,
                plotted_variables=plotted_variables,
            )
            for variable in _VARIABLE_UNITS
        }
        station = _station_for(stations, raw_location_id)
        station_name = station.get("name", station.get("location_name", location_id))
        station_name = str(station_name) if station_name is not None else location_id
        valid_total = sum(variable_summaries[name]["count"] for name in _VARIABLE_UNITS)
        missing_total = sum(variable_summaries[name]["missing"] for name in _VARIABLE_UNITS)
        location_caveats = [
            "Missing values are omitted from statistics, not filled with zero; coverage is shown per variable.",
            "Trend, split-half, seasonal, outlier, and correlation results are descriptive statistics, not causal or event determinations.",
        ]
        if not selected_dates:
            location_caveats.append("No dates remain after applying the selected date range; statistics are unavailable.")
        locations[location_id] = {
            "location_id": location_id,
            "name": station_name,
            "overview": (
                f"{station_name}: {len(selected_dates)} plotted date(s), "
                f"{valid_total} valid variable value(s), and {missing_total} missing variable slot(s)."
                if selected_dates else f"{station_name}: no plotted dates in the selected range."
            ),
            "date_range": {
                "start": _date_text(min(selected_dates)) if selected_dates else None,
                "end": _date_text(max(selected_dates)) if selected_dates else None,
            },
            "variables": variable_summaries,
            "caveats": location_caveats,
        }

    if all_selected_dates:
        observed_start = min(all_selected_dates)
        observed_end = max(all_selected_dates)
    else:
        observed_start = observed_end = None
    start_text = _date_text(requested_start) if requested_start else (
        _date_text(observed_start) if observed_start else None
    )
    end_text = _date_text(requested_end) if requested_end else (
        _date_text(observed_end) if observed_end else None
    )
    if not locations:
        overview = "No locations were selected; no statistical summaries are available."
    elif not all_selected_dates:
        overview = "No plotted dates are available in the selected range; no numerical summaries can be computed."
    else:
        overview = (
            f"Descriptive summaries for {len(locations)} selected location(s) over "
            f"{start_text} through {end_text}; missing values are omitted, not filled."
        )
    variables: Dict[str, Any] = {}
    for variable_name, unit in _VARIABLE_UNITS.items():
        entries = []
        for location_id, location in locations.items():
            detail = location["variables"][variable_name]
            minimum = detail["min"]
            maximum = detail["max"]
            change = detail["start_end_change"]
            summary_parts = [detail["overview"]]
            if detail["trend"]["statement"]:
                summary_parts.append(detail["trend"]["statement"])
            if detail["seasonal_statement"]:
                summary_parts.append(detail["seasonal_statement"])
            entries.append({
                "location_id": location_id,
                "location_name": location["name"],
                "summary": " ".join(summary_parts),
                "count": detail["count"],
                "missing_count": detail["missing"],
                "coverage_pct": detail["coverage_pct"],
                "min": ({"date": minimum["date"], "value": minimum["value"]}
                        if minimum is not None else None),
                "max": ({"date": maximum["date"], "value": maximum["value"]}
                        if maximum is not None else None),
                "mean": detail["mean"],
                "median": detail["median"],
                "change": change,
                "trend_per_year": detail["trend"]["slope_per_year"],
                "trend_direction": detail["trend"]["label"],
                "comparison": detail["half_comparison"],
                "monthly_means": {
                    **detail["monthly_means"],
                    "seasonal_statement": detail["seasonal_statement"],
                },
                "potential_outliers": detail["outliers"],
                "relationships": detail["correlations"],
                "caveats": detail["caveats"],
            })
        variables[variable_name] = {"unit": unit, "locations": entries}

    return {
        "overview": overview,
        "selected_range": {"start": start_text, "end": end_text},
        "variables": variables,
        "caveats": [
            "Summaries describe only the supplied plotted series and are not causal explanations or event determinations.",
            "Missing and invalid values remain missing; do not interpret their omission as zero or complete coverage.",
        ],
    }
