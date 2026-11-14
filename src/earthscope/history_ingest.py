"""Bounded, retry-safe ingestion of real NASA POWER daily UTC history."""

from __future__ import annotations

import argparse
import errno
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from earthscope.history_store import DATASET_ID, PROJECT_ROOT, VARIABLES, HistoryStore
from earthscope.providers.nasa_power import (
    DEFAULT_LOCATIONS,
    NasaPowerError,
    TARGET_PARAMETERS,
    clean_measurement,
    fetch_nasa_power_point,
    normalize_nasa_power_records,
)

RAW_DIRECTORY = PROJECT_ROOT / "data" / "raw" / "nasa_power_history"
COMMUNITY = "RE"
MAX_CHUNK_YEARS = 5
DEFAULT_START_DATE = date(1981, 1, 1)
OVERLAP_DAYS = 7


class HistoryIngestError(RuntimeError):
    """An unrecoverable request or payload failure during historical ingestion."""


def parse_date(value: str | date, field: str = "date") -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date()
        return date.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc


def conservative_end_date(today: Optional[date] = None) -> date:
    """Avoid the latest 60 days because NASA POWER daily products can lag."""
    current = today or datetime.now(timezone.utc).date()
    return current - timedelta(days=60)


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # Feb 29 into a non-leap year.
        return day.replace(year=day.year + years, day=28)


def date_chunks(start_date: str | date, end_date: str | date, max_years: int = MAX_CHUNK_YEARS) -> list[tuple[date, date]]:
    """Split an inclusive range into chunks spanning at most max_years calendar years."""
    start, end = parse_date(start_date), parse_date(end_date)
    if start > end:
        raise ValueError("start_date must not be after end_date")
    if max_years < 1:
        raise ValueError("max_years must be at least 1")
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, _add_years(cursor, max_years) - timedelta(days=1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def is_transient_failure(exc: BaseException) -> bool:
    """Only timeouts, common transient socket errors, HTTP 429, and HTTP 5xx retry."""
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    transient_errnos = {
        errno.EAGAIN, errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNREFUSED,
        errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EPIPE,
    }
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (TimeoutError, ConnectionError, TimeoutError)):
            return True
        if isinstance(current, urllib.error.HTTPError):
            if current.code == 429 or 500 <= current.code <= 599:
                return True
        if isinstance(current, urllib.error.URLError):
            reason = current.reason
            if isinstance(reason, BaseException):
                pending.append(reason)
            elif isinstance(reason, str) and re.search(r"timed?\s*out|temporary failure|connection reset", reason, re.I):
                return True
        if isinstance(current, OSError) and current.errno in transient_errnos:
            return True
        message = str(current)
        status = re.search(r"(?:http(?: error| status)?\s*)(\d{3})", message, re.I)
        if status:
            code = int(status.group(1))
            if code == 429 or 500 <= code <= 599:
                return True
        if re.search(r"timed?\s*out|timeout", message, re.I):
            return True
        for nested in (getattr(current, "__cause__", None), getattr(current, "__context__", None)):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def fetch_with_retries(
    fetch_func: Callable[..., dict[str, Any]], *, fetch_kwargs: Mapping[str, Any],
    sleep_func: Callable[[float], Any] = time.sleep, max_attempts: int = 4,
    base_delay: float = 1.0,
) -> dict[str, Any]:
    """Retry transient request failures at most four total attempts, with exponential backoff."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    for attempt in range(max_attempts):
        try:
            return fetch_func(**dict(fetch_kwargs))
        except Exception as exc:
            if attempt + 1 >= max_attempts or not is_transient_failure(exc):
                raise
            sleep_func(base_delay * (2 ** attempt))
    raise AssertionError("unreachable")


def _raw_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _parameter_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    api = header.get("api") if isinstance(header.get("api"), dict) else {}
    parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    source_products = header.get("sources") if isinstance(header.get("sources"), list) else []
    param_meta = {}
    for code, _canonical, _unit, _raw_unit, _description in VARIABLES:
        details = parameters.get(code)
        if isinstance(details, dict):
            param_meta[code] = {k: v for k, v in details.items() if k in {"longname", "units"}}
    return {
        "source": DATASET_ID,
        "dataset_id": DATASET_ID,
        "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "temporal_resolution": "daily",
        "meteorology_lineage": "NASA POWER meteorology blends MERRA-2 reanalysis with GEOS-IT near-real-time data; product lineage can vary by parameter.",
        "meteorology_methodology_url": "https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/",
        "api_name": api.get("name"), "api_version": api.get("version"),
        "time_standard": header.get("time_standard"), "community": header.get("community", COMMUNITY),
        "source_products": [item for item in source_products if isinstance(item, str)],
        "parameters": param_meta,
    }


def _compressed_raw_file(payload: Mapping[str, Any], location_id: str, start: date, end: date,
                         raw_directory: Path) -> tuple[str, str]:
    raw_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    safe_location = re.sub(r"[^A-Za-z0-9_.-]+", "_", location_id)
    target = raw_directory / f"{safe_location}_{start:%Y%m%d}_{end:%Y%m%d}_{digest[:16]}.json.gz"
    raw_directory.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with target.open("wb") as output:
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
                compressed.write(raw_bytes)
    try:
        stored_path = str(target.relative_to(PROJECT_ROOT))
    except ValueError:
        stored_path = str(target)
    return stored_path, digest


def _observation_rows(
    payload: Mapping[str, Any], location: Mapping[str, Any], parameters: Sequence[str],
    chunk_start: date, chunk_end: date, raw_path: str, digest: str,
) -> list[dict[str, Any]]:
    # Reuse the established client's contract checks, including UTC assertion and response shape.
    normalize_nasa_power_records(
        dict(payload), str(location["location_id"]), str(location["location_name"]),
        float(location["latitude"]), float(location["longitude"]),
    )
    properties = payload.get("properties") or {}
    param_data = properties.get("parameter") or {}
    source_metadata = _parameter_metadata(payload)
    source_metadata.update({
        "requested_start": chunk_start.isoformat(), "requested_end": chunk_end.isoformat(),
        "latitude": float(location["latitude"]), "longitude": float(location["longitude"]),
        "raw_response_path": raw_path, "raw_sha256": digest,
    })
    dates: list[date] = []
    cursor = chunk_start
    while cursor <= chunk_end:
        dates.append(cursor)
        cursor += timedelta(days=1)

    rows: list[dict[str, Any]] = []
    for requested_code in parameters:
        code = str(requested_code).upper()
        if code not in {item[0] for item in VARIABLES}:
            raise ValueError(f"Unsupported NASA POWER parameter: {requested_code!r}")
        _code, _canonical, canonical_unit, raw_unit, _description = next(
            item for item in VARIABLES if item[0] == code
        )
        values = param_data.get(code, {})
        if not isinstance(values, dict):
            values = {}
        for day in dates:
            raw = values.get(day.strftime("%Y%m%d"))
            raw_number = _raw_number(raw)
            clean = clean_measurement(raw)
            if code == "WS10M":
                normalized = round(clean * 3.6, 2) if clean is not None else None
            elif code == "PRECTOTCORR":
                normalized = round(clean, 2) if clean is not None else None
            else:
                normalized = clean
            rows.append({
                "location_id": str(location["location_id"]), "dataset_id": DATASET_ID,
                "variable_code": code, "observed_on": day.isoformat(), "resolution": "daily",
                "raw_value": raw_number, "raw_unit": raw_unit, "normalized_value": normalized,
                "canonical_unit": canonical_unit, "source_metadata": source_metadata,
                "raw_response_path": raw_path, "raw_sha256": digest,
            })
    return rows


def _updated_start(store: HistoryStore, location_id: str, parameters: Sequence[str], fallback: date) -> date:
    latest_dates = [store.latest_observed_date(location_id, parameter) for parameter in parameters]
    # Re-ingest from the earliest covered tail so lagging/missing variables are healed too.
    if not latest_dates or any(day is None for day in latest_dates):
        return fallback
    earliest_latest = min(parse_date(day) for day in latest_dates if day is not None)
    return max(fallback, earliest_latest - timedelta(days=OVERLAP_DAYS))


def ingest_history(
    start_date: str | date = DEFAULT_START_DATE,
    end_date: Optional[str | date] = None,
    *,
    locations: Optional[Sequence[Mapping[str, Any]]] = None,
    parameters: Sequence[str] = TARGET_PARAMETERS,
    update: bool = False,
    dry_run: bool = False,
    store: Optional[HistoryStore] = None,
    fetch_func: Optional[Callable[..., dict[str, Any]]] = None,
    sleep_func: Callable[[float], Any] = time.sleep,
    raw_directory: Optional[Path | str] = None,
    progress_func: Optional[Callable[[str], Any]] = None,
) -> dict[str, Any]:
    """Ingest a specified period; no API request exceeds five years."""
    requested_start = parse_date(start_date, "start_date")
    requested_end = parse_date(end_date, "end_date") if end_date is not None else conservative_end_date()
    if requested_start > requested_end:
        raise ValueError("start_date must not be after end_date")
    params = [str(parameter).upper() for parameter in parameters]
    known = {item[0] for item in VARIABLES}
    if not params or any(parameter not in known for parameter in params):
        raise ValueError(f"parameters must be selected from {sorted(known)}")
    selected_locations = [dict(location) for location in (locations or DEFAULT_LOCATIONS)]
    for location in selected_locations:
        required = ("location_id", "location_name", "latitude", "longitude")
        if any(key not in location for key in required):
            raise ValueError(f"Each location requires {', '.join(required)}")
    raw_dir = Path(raw_directory) if raw_directory is not None else RAW_DIRECTORY
    fetcher = fetch_func or fetch_nasa_power_point
    owns_store = store is None and not dry_run
    active_store = store or (HistoryStore() if not dry_run else None)

    plan = []
    for location in selected_locations:
        actual_start = _updated_start(active_store, str(location["location_id"]), params, requested_start) \
            if update and active_store else requested_start
        if actual_start <= requested_end:
            for first, last in date_chunks(actual_start, requested_end):
                plan.append({"location_id": location["location_id"], "start_date": first.isoformat(),
                             "end_date": last.isoformat(), "parameters": list(params)})
    if dry_run:
        if owns_store and active_store:
            active_store.close()
        return {"status": "dry_run", "requests_planned": len(plan), "plan": plan,
                "start_date": requested_start.isoformat(), "end_date": requested_end.isoformat(),
                "locations": [loc["location_id"] for loc in selected_locations], "parameters": params}

    assert active_store is not None
    for location in selected_locations:
        active_store.register_location(location)
    run_id = active_store.create_ingestion_run(
        requested_start.isoformat(), requested_end.isoformat(), params, len(selected_locations),
        metadata={"update": bool(update), "chunk_max_years": MAX_CHUNK_YEARS},
    )
    request_count = 0
    row_count = 0
    location_by_id = {str(location["location_id"]): location for location in selected_locations}
    try:
        for index, item in enumerate(plan, start=1):
            location = location_by_id[str(item["location_id"])]
            first, last = parse_date(item["start_date"]), parse_date(item["end_date"])
            request_count += 1
            if progress_func:
                progress_func(
                    f"[{index}/{len(plan)}] NASA POWER {location['location_id']} "
                    f"{first.isoformat()} through {last.isoformat()} ({len(params)} parameters)"
                )
            try:
                payload = fetch_with_retries(
                    fetcher,
                    fetch_kwargs={
                        "latitude": float(location["latitude"]), "longitude": float(location["longitude"]),
                        "start_date": first.strftime("%Y%m%d"), "end_date": last.strftime("%Y%m%d"),
                        "parameters": params, "community": COMMUNITY,
                    },
                    sleep_func=sleep_func,
                )
            except Exception as exc:
                raise HistoryIngestError(
                    f"NASA POWER request failed for {location['location_id']} {first}..{last}: {exc}"
                ) from exc
            if not isinstance(payload, dict):
                raise HistoryIngestError("NASA POWER response was not a JSON object")
            raw_path, digest = _compressed_raw_file(payload, str(location["location_id"]), first, last, raw_dir)
            rows = _observation_rows(payload, location, params, first, last, raw_path, digest)
            row_count += active_store.upsert_observations(rows)
        active_store.finish_ingestion_run(run_id, "completed", request_count, row_count)
        return {"status": "completed", "run_id": run_id, "requests": request_count,
                "observation_rows_upserted": row_count, "locations": len(selected_locations),
                "start_date": requested_start.isoformat(), "end_date": requested_end.isoformat()}
    except Exception as exc:
        active_store.finish_ingestion_run(run_id, "failed", request_count, row_count, str(exc))
        raise
    finally:
        if owns_store:
            active_store.close()


def _select_locations(values: Optional[Sequence[str]]) -> list[dict[str, Any]]:
    if not values:
        return [dict(location) for location in DEFAULT_LOCATIONS]
    requested = [part.strip() for value in values for part in value.split(",") if part.strip()]
    by_id = {location["location_id"]: location for location in DEFAULT_LOCATIONS}
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise ValueError(f"Unknown location ID(s): {', '.join(unknown)}")
    return [dict(by_id[location_id]) for location_id in requested]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest historical NASA POWER daily UTC observations into SQLite.")
    parser.add_argument("--start-date", help="Inclusive start date (default: 1981-01-01)")
    parser.add_argument("--end-date", help="Inclusive end date (default: UTC today minus 60 days)")
    parser.add_argument("--update", action="store_true", help="Incrementally refresh from latest coverage minus 7 days")
    parser.add_argument("--locations", nargs="+", help="Location IDs, optionally comma-separated (default: all stations)")
    parser.add_argument("--dry-run", action="store_true", help="Print request plan without API calls or database writes")
    args = parser.parse_args(argv)
    try:
        locations = _select_locations(args.locations)
        result = ingest_history(
            start_date=parse_date(args.start_date, "start_date") if args.start_date else DEFAULT_START_DATE,
            end_date=parse_date(args.end_date, "end_date") if args.end_date else None,
            locations=locations, update=args.update, dry_run=args.dry_run,
            progress_func=lambda message: print(message, file=sys.stderr, flush=True),
        )
    except (ValueError, HistoryIngestError, NasaPowerError) as exc:
        print(f"History ingestion failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI invocation
    raise SystemExit(main())
