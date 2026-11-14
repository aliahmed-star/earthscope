"""
data_loader.py - loads and validates environmental observations.

RESPONSIBILITY
    Turn raw records (from the offline demo file or an optional live provider)
    into clean, validated observation dictionaries that all other modules
    share. This module does NOT calculate risk - that is analysis.py's job.

THE SHARED OBSERVATION FORMAT (one dict per monitored location)
    location_id     str    unique identifier, e.g. "manila-ph"
    location_name   str    display name
    latitude        float  -90..90
    longitude       float  -180..180
    temperature_c   float|None   degrees Celsius
    humidity_pct    float|None   percent, 0..100
    wind_speed_kmh  float|None   km/h
    rainfall_mm     float|None   daily precipitation amount (NASA POWER: mm/day)
    observed_at     str    UTC ISO-8601, e.g. "2026-11-13T09:00:00Z"
    data_source     str    where the data came from, e.g. "demo_dataset"
    is_simulated    bool   True for demo/simulated data, False for real readings
    note            str    (optional) free text, e.g. describes a simulated event

MISSING VALUES
    A measurement that is not available is stored as None. It is NEVER
    replaced by 0, because "0 mm of rain" and "rain unknown" mean different
    things. A measurement that is present but malformed or out of range makes
    the whole record invalid (rejected with explicit error messages).

OFFLINE OPERATION
    get_observations() always works without internet: if no live provider is
    supplied, or the provider fails or returns nothing usable, it falls back
    to the local demo dataset and says so in its "notes".
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from . import config


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ObservationValidationError(ValueError):
    """Raised when one observation record is invalid.

    `errors` is a list of {"field", "code", "message"} dicts so the frontend
    can show every problem at once instead of one at a time.
    """

    def __init__(self, errors, record_id=None):
        self.errors = errors
        self.record_id = record_id
        summary = "; ".join(e["message"] for e in errors)
        super().__init__(f"Invalid observation{f' {record_id!r}' if record_id else ''}: {summary}")

    def to_dict(self):
        return {"ok": False, "error": {"code": "VALIDATION_ERROR",
                                       "message": str(self), "details": self.errors}}


class DataLoadError(RuntimeError):
    """Raised when a data file cannot be read at all (missing, not JSON, wrong shape)."""

    def to_dict(self):
        return {"ok": False, "error": {"code": "DATA_LOAD_ERROR", "message": str(self)}}


# ---------------------------------------------------------------------------
# Field-level helpers
# ---------------------------------------------------------------------------
def _error(field, code, message):
    return {"field": field, "code": code, "message": message}


def _parse_number(value):
    """Return a finite float, or raise ValueError.

    Accepts ints, floats and numeric strings ("12.5"). Rejects booleans
    (True would otherwise silently become 1.0), NaN, infinity and text.
    """
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    number = float(value)  # raises ValueError/TypeError for junk such as "abc" or []
    if math.isnan(number) or math.isinf(number):
        raise ValueError("value is not finite")
    return number


def _parse_timestamp(value):
    """Parse an ISO-8601 timestamp that includes a timezone; return UTC 'Z' string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a non-empty ISO-8601 string")
    parsed = datetime.fromisoformat(value.strip())  # understands a trailing 'Z' on Python 3.11+
    if parsed.tzinfo is None:
        raise ValueError("must include a timezone (for example 'Z' or '+02:00')")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Validation of a single observation
# ---------------------------------------------------------------------------
def validate_observation(raw):
    """Validate one raw record and return a normalised observation dict.

    Input : a dict that should follow the shared observation format.
    Output: a NEW dict containing exactly the canonical fields.
    Raises: ObservationValidationError listing every problem found.
    """
    if not isinstance(raw, dict):
        raise ObservationValidationError(
            [_error("record", "NOT_AN_OBJECT", "Observation must be a JSON object / dict.")])

    errors = []
    clean = {}

    # --- required text fields ------------------------------------------------
    for field in ("location_id", "location_name", "data_source"):
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(_error(field, "REQUIRED", f"'{field}' is required and must be non-empty text."))
        else:
            clean[field] = value.strip()

    # --- coordinates (required, range-checked) -------------------------------
    for field, (low, high) in (("latitude", (-90.0, 90.0)), ("longitude", (-180.0, 180.0))):
        if raw.get(field) is None:
            errors.append(_error(field, "REQUIRED", f"'{field}' is required."))
            continue
        try:
            number = _parse_number(raw[field])
        except (ValueError, TypeError):
            errors.append(_error(field, "MALFORMED", f"'{field}' must be a number, got {raw[field]!r}."))
            continue
        if not low <= number <= high:
            errors.append(_error(field, "OUT_OF_RANGE", f"'{field}' must be between {low} and {high}, got {number}."))
        else:
            clean[field] = number

    # --- timestamp -----------------------------------------------------------
    try:
        clean["observed_at"] = _parse_timestamp(raw.get("observed_at"))
    except (ValueError, TypeError) as exc:
        errors.append(_error("observed_at", "MALFORMED", f"'observed_at' {exc}."))

    # --- simulated flag: must be an explicit boolean -------------------------
    # We refuse to guess, so live and simulated data can never be confused.
    if not isinstance(raw.get("is_simulated"), bool):
        errors.append(_error("is_simulated", "REQUIRED", "'is_simulated' must be true or false."))
    else:
        clean["is_simulated"] = raw["is_simulated"]

    # --- measurements (optional, but if present they must be valid) ----------
    for field in config.MEASUREMENT_FIELDS:
        value = raw.get(field)
        if value is None:
            clean[field] = None  # missing stays missing - never 0
            continue
        label, unit = config.MEASUREMENT_LABELS[field]
        try:
            number = _parse_number(value)
        except (ValueError, TypeError):
            errors.append(_error(field, "MALFORMED", f"{label} must be a number, got {value!r}."))
            continue
        low, high = config.VALID_RANGES[field]
        if not low <= number <= high:
            errors.append(_error(field, "OUT_OF_RANGE",
                                 f"{label} {number:g} {unit} is outside the valid range {low:g} to {high:g} {unit}."))
        else:
            clean[field] = number

    # --- optional note -------------------------------------------------------
    if isinstance(raw.get("note"), str) and raw["note"].strip():
        clean["note"] = raw["note"].strip()

    # --- optional source metadata -------------------------------------------
    # Keep a small, JSON-safe record of the upstream API and parameter labels.
    # Do not copy arbitrary payload objects into the canonical observation.
    metadata = raw.get("source_metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            errors.append(_error("source_metadata", "MALFORMED", "'source_metadata' must be an object."))
        else:
            safe_metadata = {}
            for field in ("api_name", "api_version", "time_standard", "community"):
                value = metadata.get(field)
                if isinstance(value, str) and value.strip():
                    safe_metadata[field] = value.strip()
            products = metadata.get("source_products")
            if isinstance(products, list):
                safe_metadata["source_products"] = [p.strip() for p in products if isinstance(p, str) and p.strip()]
            parameters = metadata.get("parameters")
            if isinstance(parameters, dict):
                safe_metadata["parameters"] = {
                    name: {
                        field: value.strip()
                        for field, value in details.items()
                        if field in ("longname", "units") and isinstance(value, str) and value.strip()
                    }
                    for name, details in parameters.items()
                    if isinstance(name, str) and isinstance(details, dict)
                }
            clean["source_metadata"] = safe_metadata

    if errors:
        record_id = raw.get("location_id") if isinstance(raw.get("location_id"), str) else None
        raise ObservationValidationError(errors, record_id=record_id)
    return clean


def validate_many(raw_records):
    """Validate a list of raw records without stopping at the first bad one.

    Returns (valid, rejected):
        valid    - list of normalised observation dicts
        rejected - list of {"record": <raw>, "errors": [...]} for invalid ones
    """
    valid, rejected = [], []
    for record in raw_records:
        try:
            valid.append(validate_observation(record))
        except ObservationValidationError as exc:
            rejected.append({"record": record, "errors": exc.errors})
    return valid, rejected


# ---------------------------------------------------------------------------
# File loading and the public entry point
# ---------------------------------------------------------------------------
def load_observations_file(path):
    """Read a JSON file of the form {"observations": [ ... ]} and validate it.

    Returns (valid, rejected) as in validate_many().
    Raises DataLoadError if the file is missing, not valid JSON or has the wrong shape.
    """
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        raise DataLoadError(f"Data file not found: {path}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise DataLoadError(f"Could not read data file {path}: {exc}") from exc

    records = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise DataLoadError(f"{path} must contain an object with an 'observations' list.")
    return validate_many(records)


def load_demo_observations(path=None):
    """Load the offline demonstration dataset (no internet needed).

    Raises DataLoadError if no valid observation could be loaded.
    """
    valid, rejected = load_observations_file(path or config.DEMO_DATA_PATH)
    if not valid:
        raise DataLoadError("The demo dataset contains no valid observations.")
    return valid, rejected


def get_observations(provider=None, demo_path=None):
    """Main entry point for the application: always returns usable data.

    provider: optional zero-argument function returning a list of raw records
              from a live source. It is OPTIONAL and replaceable; any
              exception, or a result with no valid records, triggers the
              offline fallback instead of breaking the dashboard.

    Returns a dict:
        {
          "observations": [validated observation dicts],
          "rejected":     [{"record", "errors"}, ...],   # invalid records, never hidden
          "mode":         "live" | "demo",
          "notes":        [human-readable messages about fallbacks/problems],
        }
    """
    notes = []
    if provider is not None:
        try:
            valid, rejected = validate_many(provider())
            if valid:
                return {"observations": valid, "rejected": rejected, "mode": "live", "notes": notes}
            notes.append("Live provider returned no valid observations; using offline demo data.")
        except Exception as exc:  # deliberately broad: ANY provider failure must not block the dashboard
            notes.append(f"Live provider failed ({type(exc).__name__}: {exc}); using offline demo data.")

    valid, rejected = load_demo_observations(demo_path)
    if provider is None:
        notes.append("No live provider configured; using offline demo data.")
    return {"observations": valid, "rejected": rejected, "mode": "demo", "notes": notes}
