"""dashboard_service.py - the bridge between EARTHSCOPE (system logic) and the web API.

Pure Python (no FastAPI here) so it can be tested on its own.

Pipeline, using YOUR existing modules:
    NASA POWER provider  ->  data_loader.get_observations()  ->  analysis.assess_observation()
                                                              ->  incidents.IncidentStore
"""
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from earthscope import config  # noqa: E402
from earthscope.analysis import assess_observation  # noqa: E402
from earthscope.data_loader import DataLoadError, get_observations, load_demo_observations  # noqa: E402
from earthscope.incidents import IncidentError, IncidentStore  # noqa: E402
from earthscope.providers import nasa_power  # noqa: E402
from earthscope.history_store import HistoryStore  # noqa: E402
from earthscope.graph_summaries import summarize_dashboard_series  # noqa: E402

MAX_DAYS = 31          # keeps NASA requests fast and charts readable
MAX_HISTORY_DAYS = 3660  # ten-year window per historical dashboard request
CACHE_TTL = 600        # seconds: don't hit NASA again for the same query
MAX_CACHE_ENTRIES = 128
DEFAULT_COUNT = 3      # stations selected by default in live mode

# One incident registry per mode, so simulated incidents never mix with real ones.
_stores = {"live": IncidentStore(), "demo": IncidentStore()}
_cache = {}
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------
def list_stations():
    """All known stations: NASA default locations + any extra ones in the demo file."""
    stations = {}
    for loc in nasa_power.DEFAULT_LOCATIONS:
        stations[loc["location_id"]] = {
            "id": loc["location_id"], "name": loc["location_name"],
            "country_name": loc.get("country_name", ""), "country_code": loc.get("country_code", ""),
            "lat": loc["latitude"], "lon": loc["longitude"], "in_demo": False,
        }
    try:
        demo, _ = load_demo_observations()
    except DataLoadError:
        demo = []
    for obs in demo:
        station = stations.setdefault(obs["location_id"], {
            "id": obs["location_id"], "name": obs["location_name"],
            "lat": obs["latitude"], "lon": obs["longitude"], "in_demo": False,
        })
        station["in_demo"] = True
    return list(stations.values())


# ---------------------------------------------------------------------------
# Loading observations
# ---------------------------------------------------------------------------
def _fetch_one(loc, start, end, fetch):
    try:
        raw = fetch(latitude=loc["lat"], longitude=loc["lon"],
                    start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
        return nasa_power.normalize_nasa_power_records(
            raw, loc["id"], loc["name"], loc["lat"], loc["lon"]), None
    except Exception as exc:  # one failing station must not break the others
        return [], f"{loc['name']}: {exc}"


def _live_observations(locations, start, end, fetch):
    """Fetch every station in parallel; reuse the existing get_observations() fallback."""
    errors = []

    def provider():
        with ThreadPoolExecutor(max_workers=min(5, len(locations))) as pool:
            results = list(pool.map(lambda loc: _fetch_one(loc, start, end, fetch), locations))
        records = []
        for obs, err in results:
            records.extend(obs)
            if err:
                errors.append(err)
        return records

    result = get_observations(provider=provider)
    if errors:
        result["notes"] = [f"NASA POWER request failed for {e}" for e in errors] + result["notes"]
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def _series_for(observations):
    out = {"dates": [], "temperature": [], "humidity": [], "wind": [], "rainfall": []}
    for obs in sorted(observations, key=lambda o: o["observed_at"]):
        out["dates"].append(obs["observed_at"][:10])
        out["temperature"].append(obs["temperature_c"])
        out["humidity"].append(obs["humidity_pct"])
        out["wind"].append(obs["wind_speed_kmh"])
        out["rainfall"].append(obs["rainfall_mm"])
    return out


def _align_series(series):
    """Align every location to the union of available UTC dates.

    NASA may omit dates with unavailable values. Without this alignment, the
    frontend's shared x-axis could pair one location's value with another
    location's date. Missing dates are kept as None, never filled with zero.
    """
    fields = ("temperature", "humidity", "wind", "rainfall")
    dates = sorted({day for item in series.values() for day in item["dates"]})
    aligned = {}
    for location_id, item in series.items():
        by_date = {}
        for index, day in enumerate(item["dates"]):
            by_date[day] = {field: item[field][index] for field in fields}
        aligned[location_id] = {"dates": dates}
        for field in fields:
            aligned[location_id][field] = [
                by_date.get(day, {}).get(field) for day in dates
            ]
    return aligned


def _latest_with_data(observations):
    ordered = sorted(observations, key=lambda o: o["observed_at"])
    for obs in reversed(ordered):
        if any(obs.get(f) is not None for f in config.MEASUREMENT_FIELDS):
            return obs
    return ordered[-1]


def _historical_result(location_ids, start, end):
    """Read only persisted NASA records; historical mode never falls back to demo."""
    if start is not None and end is not None:
        if start > end:
            raise ValueError("start_date must be on or before end_date.")
        if (end - start).days + 1 > MAX_HISTORY_DAYS:
            raise ValueError(f"Historical requests are limited to {MAX_HISTORY_DAYS} days (about ten years).")
    store = HistoryStore()
    availability = store.availability()
    coverage_by_id = {
        item["location_id"]: item for item in availability.get("coverage", [])
        if item.get("min_date") and item.get("max_date")
    }
    missing = [location_id for location_id in location_ids if location_id not in coverage_by_id]
    if missing:
        raise DataLoadError(
            "No NASA POWER historical archive is available for: " + ", ".join(missing)
        )

    selected_coverage = [coverage_by_id[location_id] for location_id in location_ids]
    earliest = max(date.fromisoformat(item["min_date"]) for item in selected_coverage)
    latest = min(date.fromisoformat(item["max_date"]) for item in selected_coverage)
    if earliest > latest:
        raise DataLoadError("The selected locations do not have overlapping historical coverage.")

    notes = []
    end = end or latest
    start = start or max(earliest, end - timedelta(days=365))
    if end < start:
        raise ValueError("start_date must be on or before end_date.")
    if start < earliest:
        start = earliest
        notes.append(f"Start date clipped to the earliest common archived day ({earliest.isoformat()}).")
    if end > latest:
        end = latest
        notes.append(f"End date clipped to the latest common archived day ({latest.isoformat()}).")
    if (end - start).days + 1 > MAX_HISTORY_DAYS:
        raise ValueError(f"Historical requests are limited to {MAX_HISTORY_DAYS} days (about ten years).")

    observations = store.dashboard_observations(location_ids, start.isoformat(), end.isoformat())
    if not observations:
        raise DataLoadError("No archived NASA POWER observations exist in the selected date range.")
    return {
        "mode": "historical",
        "observations": observations,
        "notes": notes,
        "rejected": [],
        "retrieved_at": availability.get("latest_retrieved_at"),
        "source_metadata": observations[0].get("source_metadata"),
    }, start, end


def build_dashboard(mode="live", station_ids=None, start=None, end=None, fetch=None):
    """Return everything the frontend needs in one JSON-friendly dict."""
    if mode not in ("live", "demo", "historical"):
        raise ValueError("mode must be 'live', 'demo', or 'historical'.")
    fetch = fetch or nasa_power.fetch_nasa_power_point
    stations = {s["id"]: s for s in list_stations()}
    live_ids = [s["location_id"] for s in nasa_power.DEFAULT_LOCATIONS]
    selected_ids = list(dict.fromkeys(station_ids or []))
    unknown_ids = [i for i in selected_ids if i not in stations]
    if unknown_ids:
        raise ValueError(f"Unknown location id(s): {', '.join(unknown_ids)}.")
    ids = selected_ids or live_ids[:DEFAULT_COUNT]

    extra_notes = []
    if mode == "historical":
        result, start, end = _historical_result(ids, start, end)
    else:
        today = date.today()
        end = min(end or today - timedelta(days=2), today)   # NASA data lags a few days
        start = start or end - timedelta(days=13)
        if start > end:
            raise ValueError("start_date must be on or before end_date.")
        if (end - start).days >= MAX_DAYS:
            start = end - timedelta(days=MAX_DAYS - 1)
            extra_notes.append(f"Date range limited to {MAX_DAYS} days.")

    if mode == "live":
        key = (tuple(sorted(ids)), start, end, fetch)
        now = time.monotonic()
        with _cache_lock:
            for stale_key, (cached_at, _) in list(_cache.items()):
                if now - cached_at >= CACHE_TTL:
                    _cache.pop(stale_key, None)
            hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            result = hit[1]
        else:
            result = _live_observations([stations[i] for i in ids], start, end, fetch)
            if result["mode"] == "live":
                result["retrieved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                with _cache_lock:
                    _cache[key] = (time.monotonic(), result)
                    while len(_cache) > MAX_CACHE_ENTRIES:
                        oldest = min(_cache, key=lambda cached_key: _cache[cached_key][0])
                        _cache.pop(oldest, None)
    elif mode == "demo":
        result = get_observations()
        result["notes"] = ["Demo mode: simulated offline dataset (date range is ignored)."]

    by_loc = {}
    for obs in result["observations"]:
        by_loc.setdefault(obs["location_id"], []).append(obs)
    if result["mode"] == "demo":
        # An unfiltered direct demo request keeps the complete scenario. When
        # the UI passes locations, preserve that selection even on fallback.
        shown = [i for i in ids if i in by_loc] if selected_ids else list(by_loc)
        if mode == "live" and selected_ids and not shown:
            extra_notes.append("No offline demonstration records match the selected location(s).")
    else:
        shown = [i for i in ids if i in by_loc]

    out_stations, series, assessments = [], {}, []
    for loc_id in shown:
        obs_list = by_loc[loc_id]
        latest = _latest_with_data(obs_list)
        a = assess_observation(latest)
        assessments.append(a)
        series[loc_id] = _series_for(obs_list)
        out_stations.append({
            "id": loc_id, "name": latest["location_name"],
            "lat": latest["latitude"], "lon": latest["longitude"],
            "risk_level": a["risk_level"], "risk_rank": a["risk_rank"], "alert": a["alert"],
            "primary_hazard": a["primary_hazard"], "summary": a["summary"],
            "reasons": a["reasons"], "limitations": a["limitations"],
            "measurements": a["measurements"], "observed_at": a["observed_at"],
            "is_simulated": a["is_simulated"], "data_source": a["data_source"],
            "source_metadata": a.get("source_metadata"),
        })

    series = _align_series(series)
    if result["mode"] in _stores:
        incident_store = _stores[result["mode"]]
        incident_store.register_alerts(assessments)
        incidents = [i for i in incident_store.list_incidents() if i["location_id"] in set(shown)]
    else:
        incidents = []  # historical review does not create response incidents

    graph_summaries = summarize_dashboard_series(
        series, out_stations, start.isoformat(), end.isoformat()
    )

    return {
        "mode": result["mode"],
        "requested_mode": mode,
        "is_simulated": any(s["is_simulated"] for s in out_stations),
        "notes": extra_notes + result["notes"],
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "retrieved_at": result.get("retrieved_at"),
        "source_metadata": next(
            (station["source_metadata"] for station in out_stations if station.get("source_metadata")),
            None,
        ),
        "stations": out_stations,
        "series": series,
        "graph_summaries": graph_summaries,
        "incidents": incidents,
        "rejected": len(result["rejected"]),
        "threshold_set": config.THRESHOLD_SET_NAME,
        "disclaimer": config.PROTOTYPE_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Incident workflow (simulated response only changes a status field)
# ---------------------------------------------------------------------------
def _store(mode):
    if mode not in _stores:
        raise IncidentError("INVALID_ASSESSMENT", f"Unknown mode {mode!r}.")
    return _stores[mode]


def list_all_incidents(mode=None):
    modes = [mode] if mode else list(_stores)
    return [i for m in modes for i in _store(m).list_incidents()]


def incident_action(mode, incident_id, action, note=None):
    store = _store(mode)
    if action == "start":
        return store.start_response(incident_id, note)
    if action == "resolve":
        return store.resolve_incident(incident_id, note)
    if action == "note":
        return store.add_note(incident_id, note)
    raise IncidentError("INVALID_TRANSITION", f"Unknown action {action!r}.")
