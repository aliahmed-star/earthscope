"""SQLite persistence and read API for the EARTHSCOPE daily history archive."""

from __future__ import annotations

import hashlib
import json
import math
import os
import calendar
import sqlite3
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from earthscope.providers.nasa_power import DEFAULT_LOCATIONS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "historical" / "earthscope_power.sqlite3"
MIGRATION_PATH = PROJECT_ROOT / "data" / "migrations" / "001_historical_archive.sql"
PROVENANCE_MIGRATION_PATH = PROJECT_ROOT / "data" / "migrations" / "002_normalize_history_provenance.sql"
COUNTRY_MIGRATION_PATH = PROJECT_ROOT / "data" / "migrations" / "003_location_country_metadata.sql"
DATASET_ID = "NASA_POWER_DAILY"

VARIABLES = (
    ("T2M", "temperature_c", "°C", "°C", "Temperature at 2 meters"),
    ("RH2M", "humidity_pct", "%", "%", "Relative humidity at 2 meters"),
    ("WS10M", "wind_speed_kmh", "km/h", "m/s", "Wind speed at 10 meters"),
    ("PRECTOTCORR", "rainfall_mm", "mm/day", "mm/day", "Corrected precipitation"),
)
_VARIABLE_LOOKUP = {
    alias.lower(): (code, canonical, unit, raw_unit)
    for code, canonical, unit, raw_unit, _description in VARIABLES
    for alias in (code, canonical)
}


def _date_string(value: Any, field: str = "date") -> str:
    """Validate a date-like value and return the archive's YYYY-MM-DD form."""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        return date.fromisoformat(text).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD (or YYYYMMDD), got {value!r}") from exc


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), default=str)


def _decode_json(value: Optional[str]) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"unparsed": value}


class HistoryStore:
    """Connection-owning SQLite store. All dates are UTC daily keys (YYYY-MM-DD)."""

    def __init__(self, path: Optional[os.PathLike | str] = None):
        configured = path if path is not None else os.environ.get("EARTHSCOPE_HISTORY_DB")
        self.path = Path(configured).expanduser() if configured and str(configured) != ":memory:" else configured
        if self.path is None:
            self.path = DEFAULT_DB_PATH
        if str(self.path) != ":memory:":
            self.path = Path(self.path).resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        if str(self.path) != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        if not MIGRATION_PATH.exists():
            raise FileNotFoundError(f"History schema migration not found: {MIGRATION_PATH}")
        self._connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
        schema_version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if schema_version < 2:
            if not PROVENANCE_MIGRATION_PATH.exists():
                raise FileNotFoundError(f"History provenance migration not found: {PROVENANCE_MIGRATION_PATH}")
            self._connection.executescript(PROVENANCE_MIGRATION_PATH.read_text(encoding="utf-8"))
            if str(self.path) != ":memory:":
                self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._connection.execute("VACUUM")
                self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        schema_version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if schema_version < 3:
            if not COUNTRY_MIGRATION_PATH.exists():
                raise FileNotFoundError(f"History country migration not found: {COUNTRY_MIGRATION_PATH}")
            self._connection.executescript(COUNTRY_MIGRATION_PATH.read_text(encoding="utf-8"))
        self._seed_reference_data()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def _seed_reference_data(self) -> None:
        with self._lock, self._connection:
            self._connection.executemany(
                """INSERT INTO variables(variable_code, canonical_name, canonical_unit, raw_unit, description)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT(variable_code) DO UPDATE SET
                   canonical_name=excluded.canonical_name, canonical_unit=excluded.canonical_unit,
                   raw_unit=excluded.raw_unit, description=excluded.description""",
                VARIABLES,
            )
            self._connection.execute(
                """INSERT INTO datasets(dataset_id, source_code, resolution, description, source_url)
                   VALUES (?, ?, 'daily', ?, ?) ON CONFLICT(dataset_id) DO NOTHING""",
                (DATASET_ID, DATASET_ID, "NASA POWER Daily Point API, UTC daily data",
                 "https://power.larc.nasa.gov/api/temporal/daily/point"),
            )
        for location in DEFAULT_LOCATIONS:
            self.register_location(location)

    @staticmethod
    def resolve_variable(variable: str) -> tuple[str, str, str, str]:
        try:
            return _VARIABLE_LOOKUP[str(variable).lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported NASA POWER variable: {variable!r}") from exc

    def register_location(self, location: Mapping[str, Any]) -> None:
        required = ("location_id", "location_name", "latitude", "longitude")
        missing = [key for key in required if key not in location]
        if missing:
            raise ValueError(f"Location is missing required fields: {', '.join(missing)}")
        latitude, longitude = float(location["latitude"]), float(location["longitude"])
        if not (math.isfinite(latitude) and -90.0 <= latitude <= 90.0):
            raise ValueError("latitude must be finite and between -90 and 90 degrees")
        if not (math.isfinite(longitude) and -180.0 <= longitude <= 180.0):
            raise ValueError("longitude must be finite and between -180 and 180 degrees")
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO locations(location_id, location_name, latitude, longitude)
                   VALUES (?, ?, ?, ?) ON CONFLICT(location_id) DO UPDATE SET
                   location_name=excluded.location_name, latitude=excluded.latitude,
                   longitude=excluded.longitude, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
                (str(location["location_id"]), str(location["location_name"]), latitude, longitude),
            )
            country_name = str(location.get("country_name") or "")
            country_code = str(location.get("country_code") or "").upper()
            self._connection.execute(
                """UPDATE locations SET country_name=?, country_code=? WHERE location_id=?""",
                (country_name, country_code, str(location["location_id"])),
            )

    def latest_observed_date(self, location_id: str, variable: str, dataset_id: str = DATASET_ID) -> Optional[str]:
        code, *_ = self.resolve_variable(variable)
        row = self._connection.execute(
            "SELECT MAX(observed_on) AS latest FROM observations WHERE location_id=? AND variable_code=? AND dataset_id=?",
            (location_id, code, dataset_id),
        ).fetchone()
        return row["latest"] if row else None

    def create_ingestion_run(
        self, start_date: str, end_date: str, parameters: Sequence[str], location_count: int,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO ingestion_runs(run_id, started_at, status, start_date, end_date,
                   location_count, parameters_json, metadata_json) VALUES (?, ?, 'running', ?, ?, ?, ?, ?)""",
                (run_id, _utc_now(), _date_string(start_date, "start_date"), _date_string(end_date, "end_date"),
                 int(location_count), _json(list(parameters)), _json(metadata)),
            )
        return run_id

    def finish_ingestion_run(
        self, run_id: str, status: str, request_count: int = 0, observation_rows: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        if status not in {"completed", "failed", "dry_run"}:
            raise ValueError("run status must be completed, failed, or dry_run")
        with self._lock, self._connection:
            self._connection.execute(
                """UPDATE ingestion_runs SET finished_at=?, status=?, request_count=?,
                   observation_rows=?, error_message=? WHERE run_id=?""",
                (_utc_now(), status, int(request_count), int(observation_rows), error_message, run_id),
            )

    def upsert_observations(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Insert or refresh normalized rows while retaining raw values and provenance."""
        if not rows:
            return 0
        packed = []
        source_responses: dict[str, tuple[str, Optional[str], Optional[str], str]] = {}
        for row in rows:
            variable_code, canonical_name, canonical_unit, default_raw_unit = self.resolve_variable(
                str(row["variable_code"])
            )
            raw_value = row.get("raw_value")
            normalized_value = row.get("normalized_value")
            metadata_json = _json(row.get("source_metadata"))
            raw_path = str(row["raw_response_path"]) if row.get("raw_response_path") is not None else None
            raw_sha256 = str(row["raw_sha256"]) if row.get("raw_sha256") is not None else None
            if raw_sha256:
                source_key = f"sha256:{raw_sha256}"
            else:
                digest = hashlib.sha256(f"{metadata_json}\0{raw_path or ''}".encode("utf-8")).hexdigest()
                source_key = f"metadata:{digest}"
            source_responses[source_key] = (source_key, raw_sha256, raw_path, metadata_json)
            packed.append((
                str(row["location_id"]), str(row.get("dataset_id", DATASET_ID)), variable_code,
                _date_string(row["observed_on"], "observed_on"), str(row.get("resolution", "daily")),
                float(raw_value) if raw_value is not None else None, str(row.get("raw_unit") or default_raw_unit),
                float(normalized_value) if normalized_value is not None else None,
                str(row.get("canonical_unit") or canonical_unit), source_key,
            ))
        with self._lock, self._connection:
            self._connection.executemany(
                """INSERT INTO source_responses(source_key, raw_sha256, raw_response_path, source_metadata_json)
                   VALUES (?, ?, ?, ?) ON CONFLICT(source_key) DO UPDATE SET
                   raw_sha256=excluded.raw_sha256, raw_response_path=excluded.raw_response_path,
                   source_metadata_json=excluded.source_metadata_json""",
                list(source_responses.values()),
            )
            source_ids = {
                source_key: self._connection.execute(
                    "SELECT source_response_id FROM source_responses WHERE source_key=?", (source_key,)
                ).fetchone()[0]
                for source_key in source_responses
            }
            self._connection.executemany(
                """INSERT INTO observations(location_id, dataset_id, variable_code, observed_on, resolution,
                   raw_value, raw_unit, normalized_value, canonical_unit, source_response_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(location_id, dataset_id, variable_code, observed_on, resolution) DO UPDATE SET
                   raw_value=excluded.raw_value, raw_unit=excluded.raw_unit,
                   normalized_value=excluded.normalized_value, canonical_unit=excluded.canonical_unit,
                   source_response_id=excluded.source_response_id,
                   ingested_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
                [(*row[:-1], source_ids[row[-1]]) for row in packed],
            )
        return len(packed)

    def availability(self) -> dict[str, Any]:
        total = self._connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        last_run = self._connection.execute(
            "SELECT run_id, finished_at, status, start_date, end_date, request_count, observation_rows "
            "FROM ingestion_runs ORDER BY COALESCE(finished_at, started_at) DESC LIMIT 1"
        ).fetchone()
        location_rows = self._connection.execute(
            "SELECT location_id, location_name, country_name, country_code, latitude, longitude "
            "FROM locations ORDER BY location_id"
        ).fetchall()
        coverage = []
        for loc in location_rows:
            variables = []
            common_complete_years = None
            for code, canonical_name, unit, _raw_unit, _description in VARIABLES:
                row = self._connection.execute(
                    """SELECT MIN(observed_on) AS min_date, MAX(observed_on) AS max_date,
                       COUNT(*) AS record_count, SUM(CASE WHEN normalized_value IS NULL THEN 1 ELSE 0 END) AS missing_count
                       FROM observations WHERE location_id=? AND variable_code=? AND resolution='daily'""",
                    (loc["location_id"], code),
                ).fetchone()
                year_coverage = self._complete_years(loc["location_id"], code)
                complete_years = [item["year"] for item in year_coverage if item["complete"]]
                variables.append({
                    "variable_code": code, "canonical_name": canonical_name, "unit": unit,
                    "min_date": row["min_date"], "max_date": row["max_date"],
                    "record_count": int(row["record_count"]), "missing_count": int(row["missing_count"] or 0),
                    "complete_years": complete_years, "year_coverage": year_coverage,
                })
                years = set(complete_years)
                common_complete_years = years if common_complete_years is None else common_complete_years & years
            all_dates = self._connection.execute(
                "SELECT MIN(observed_on), MAX(observed_on) FROM observations WHERE location_id=?",
                (loc["location_id"],),
            ).fetchone()
            common_complete_years = sorted(common_complete_years or set())
            coverage.append({
                "location_id": loc["location_id"], "name": loc["location_name"],
                "country_name": loc["country_name"], "country_code": loc["country_code"],
                "lat": loc["latitude"], "lon": loc["longitude"],
                "min_date": all_dates[0], "max_date": all_dates[1], "variables": variables,
                "common_complete_years": common_complete_years,
                "qualified_10_complete_years": len(common_complete_years) >= 10,
            })
        latest_run = dict(last_run) if last_run else None
        return {
            "total_observation_rows": int(total),
            "coverage": coverage,
            "latest_retrieved_at": latest_run.get("finished_at") if latest_run else None,
            "latest_ingestion_run": latest_run,
        }

    def _complete_years(self, location_id: str, variable_code: str) -> list[dict[str, Any]]:
        """Return exact calendar-year row/value coverage; no date gaps are imputed."""
        rows = self._connection.execute(
            """SELECT substr(observed_on, 1, 4) AS year, COUNT(*) AS row_count,
                      COUNT(DISTINCT observed_on) AS distinct_days,
                      COUNT(normalized_value) AS valid_count
               FROM observations WHERE location_id=? AND variable_code=? AND resolution='daily'
               GROUP BY substr(observed_on, 1, 4) ORDER BY year""",
            (location_id, variable_code),
        ).fetchall()
        result = []
        for row in rows:
            try:
                year = int(row["year"])
            except (TypeError, ValueError):
                continue
            expected = 366 if calendar.isleap(year) else 365
            valid_count = int(row["valid_count"])
            row_count = int(row["row_count"])
            distinct_days = int(row["distinct_days"])
            result.append({
                "year": year, "expected_days": expected, "record_count": row_count,
                "valid_days": valid_count,
                "completeness_pct": round(100.0 * valid_count / expected, 3),
                "complete": row_count == expected and distinct_days == expected and valid_count == expected,
            })
        return result

    def query_observations(
        self, location_id: str, variable: str, start_date: str, end_date: str,
        resolution: str = "daily", limit: int = 50000,
    ) -> dict[str, Any]:
        code, canonical, _unit, _raw_unit = self.resolve_variable(variable)
        start, end = _date_string(start_date, "start_date"), _date_string(end_date, "end_date")
        if start > end:
            raise ValueError("start_date must not be after end_date")
        if int(limit) <= 0:
            raise ValueError("limit must be positive")
        rows = self._connection.execute(
            """SELECT o.observed_on, o.normalized_value, o.raw_value, o.raw_unit, o.canonical_unit,
               o.dataset_id, o.ingested_at, s.raw_response_path, s.raw_sha256,
               d.source_code, s.source_metadata_json FROM observations o JOIN datasets d USING(dataset_id)
               LEFT JOIN source_responses s USING(source_response_id)
               WHERE o.location_id=? AND o.variable_code=? AND o.resolution=?
                 AND o.observed_on BETWEEN ? AND ? ORDER BY o.observed_on LIMIT ?""",
            (location_id, code, resolution, start, end, int(limit)),
        ).fetchall()
        return {"location_id": location_id, "variable": canonical, "variable_code": code,
                "resolution": resolution, "rows": [
                    {"observed_on": row["observed_on"], "value": row["normalized_value"],
                     "raw_value": row["raw_value"], "raw_unit": row["raw_unit"],
                     "unit": row["canonical_unit"], "source": row["source_code"],
                     "dataset_id": row["dataset_id"], "ingested_at": row["ingested_at"],
                     "raw_response_path": row["raw_response_path"], "raw_sha256": row["raw_sha256"],
                     "metadata": _decode_json(row["source_metadata_json"])}
                    for row in rows
                ]}

    def variable_series(
        self, location_id: str, variable: str, start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        code, _canonical, _unit, _raw_unit = self.resolve_variable(variable)
        clauses, args = ["location_id=?", "variable_code=?", "resolution='daily'"], [location_id, code]
        if start_date is not None:
            clauses.append("observed_on>=?")
            args.append(_date_string(start_date, "start_date"))
        if end_date is not None:
            clauses.append("observed_on<=?")
            args.append(_date_string(end_date, "end_date"))
        rows = self._connection.execute(
            f"SELECT observed_on, normalized_value FROM observations WHERE {' AND '.join(clauses)} ORDER BY observed_on",
            args,
        ).fetchall()
        return [{"date": row["observed_on"], "value": row["normalized_value"]} for row in rows]

    def dashboard_observations(
        self, location_ids: Sequence[str] | str, start_date: str, end_date: str,
    ) -> list[dict[str, Any]]:
        ids = [location_ids] if isinstance(location_ids, str) else list(location_ids)
        if not ids:
            return []
        start, end = _date_string(start_date, "start_date"), _date_string(end_date, "end_date")
        if start > end:
            raise ValueError("start_date must not be after end_date")
        marks = ",".join("?" for _ in ids)
        rows = self._connection.execute(
            f"""SELECT l.location_id, l.location_name, l.latitude, l.longitude, o.observed_on,
                v.canonical_name, o.normalized_value, s.source_metadata_json
                FROM observations o JOIN locations l USING(location_id) JOIN variables v USING(variable_code)
                LEFT JOIN source_responses s USING(source_response_id)
                WHERE o.location_id IN ({marks}) AND o.resolution='daily'
                  AND o.observed_on BETWEEN ? AND ? ORDER BY l.location_id, o.observed_on, v.variable_code""",
            [*ids, start, end],
        ).fetchall()
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["location_id"], row["observed_on"])
            if key not in grouped:
                grouped[key] = {
                    "location_id": row["location_id"], "location_name": row["location_name"],
                    "latitude": row["latitude"], "longitude": row["longitude"],
                    "observed_at": f"{row['observed_on']}T00:00:00Z",
                    "temperature_c": None, "humidity_pct": None, "wind_speed_kmh": None, "rainfall_mm": None,
                    "data_source": DATASET_ID, "source_metadata": _decode_json(row["source_metadata_json"]),
                    "is_simulated": False,
                }
            grouped[key][row["canonical_name"]] = row["normalized_value"]
            if not grouped[key]["source_metadata"]:
                grouped[key]["source_metadata"] = _decode_json(row["source_metadata_json"])
        return list(grouped.values())

    def register_model_version(
        self, model_version: Optional[Mapping[str, Any] | str] = None, *,
        model_version_id: Optional[str] = None, model_name: Optional[str] = None,
        version: Optional[str] = None, training_start: Optional[str] = None,
        training_end: Optional[str] = None, metadata: Optional[Mapping[str, Any]] = None,
        **extra: Any,
    ) -> str:
        if isinstance(model_version, Mapping):
            values = dict(model_version)
            model_version_id = model_version_id or values.get("model_version_id") or values.get("id")
            model_name = model_name or values.get("model_name") or values.get("name")
            version = version or values.get("version")
            training_start = training_start or values.get("training_start")
            training_end = training_end or values.get("training_end")
            metadata = metadata or values.get("metadata")
            extra = {**{k: v for k, v in values.items() if k not in {
                "model_version_id", "id", "model_name", "name", "version", "training_start", "training_end", "metadata"
            }}, **extra}
        elif isinstance(model_version, str):
            model_version_id = model_version_id or model_version
        model_name = model_name or extra.pop("name", None)
        version = str(version or extra.pop("version", "1"))
        if not model_name:
            if model_version_id:
                model_name = str(model_version_id)
            else:
                raise ValueError("model_name (or model_version_id) is required")
        model_name = str(model_name)
        model_version_id = str(model_version_id or f"{model_name}:{version}")
        combined_metadata = {**(dict(metadata) if metadata else {}), **extra}
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO model_versions(model_version_id, model_name, version, training_start,
                   training_end, metadata_json) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(model_version_id) DO UPDATE SET model_name=excluded.model_name,
                   version=excluded.version, training_start=excluded.training_start,
                   training_end=excluded.training_end, metadata_json=excluded.metadata_json""",
                (model_version_id, model_name, version,
                 _date_string(training_start, "training_start") if training_start else None,
                 _date_string(training_end, "training_end") if training_end else None, _json(combined_metadata)),
            )
        return model_version_id

    def register_evaluation(
        self, evaluation: Optional[Mapping[str, Any]] = None, *,
        evaluation_id: Optional[str] = None, model_version_id: Optional[str] = None,
        evaluation_name: str = "default", evaluated_at: Optional[str] = None,
        dataset_id: str = "", metrics: Optional[Mapping[str, Any]] = None,
        metadata: Optional[Mapping[str, Any]] = None, **extra: Any,
    ) -> str:
        values = dict(evaluation) if isinstance(evaluation, Mapping) else {}
        evaluation_id = evaluation_id or values.get("evaluation_id") or values.get("id")
        model_version_id = model_version_id or values.get("model_version_id")
        evaluation_name = str(values.get("evaluation_name", evaluation_name))
        evaluated_at = evaluated_at or values.get("evaluated_at") or _utc_now()
        dataset_id = str(values.get("dataset_id", dataset_id))
        metrics = metrics or values.get("metrics") or {}
        metadata = metadata or values.get("metadata") or {}
        extra = {**{k: v for k, v in values.items() if k not in {
            "evaluation_id", "id", "model_version_id", "evaluation_name", "evaluated_at", "dataset_id", "metrics", "metadata"
        }}, **extra}
        if not model_version_id:
            raise ValueError("model_version_id is required")
        stamp = str(evaluated_at)
        stable = f"{model_version_id}|{evaluation_name}|{stamp}|{dataset_id}"
        evaluation_id = str(evaluation_id or hashlib.sha256(stable.encode()).hexdigest()[:32])
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO model_evaluations(evaluation_id, model_version_id, evaluation_name,
                   evaluated_at, dataset_id, metrics_json, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(model_version_id, evaluation_name, evaluated_at, dataset_id) DO UPDATE SET
                   metrics_json=excluded.metrics_json, metadata_json=excluded.metadata_json""",
                (evaluation_id, str(model_version_id), evaluation_name, stamp, dataset_id,
                 _json(dict(metrics)), _json({**dict(metadata), **extra})),
            )
            row = self._connection.execute(
                "SELECT evaluation_id FROM model_evaluations WHERE model_version_id=? AND evaluation_name=? AND evaluated_at=? AND dataset_id=?",
                (str(model_version_id), evaluation_name, stamp, dataset_id),
            ).fetchone()
        return row["evaluation_id"]

    def record_prediction(
        self, prediction: Optional[Mapping[str, Any]] = None, *,
        prediction_id: Optional[str] = None, model_version_id: Optional[str] = None,
        location_id: Optional[str] = None, variable: Optional[str] = None,
        target_date: Optional[str] = None, generated_at: Optional[str] = None,
        horizon_days: int = 0, predicted_value: Optional[float] = None,
        value: Optional[float] = None, unit: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None, **extra: Any,
    ) -> str:
        values = dict(prediction) if isinstance(prediction, Mapping) else {}
        prediction_id = prediction_id or values.get("prediction_id") or values.get("id")
        model_version_id = model_version_id or values.get("model_version_id")
        location_id = location_id or values.get("location_id")
        variable = variable or values.get("variable_code") or values.get("variable")
        target_date = target_date or values.get("target_date")
        generated_at = generated_at or values.get("generated_at") or _utc_now()
        horizon_days = int(values.get("horizon_days", horizon_days))
        predicted_value = predicted_value if predicted_value is not None else value
        if predicted_value is None:
            predicted_value = values.get("predicted_value", values.get("value"))
        unit = unit or values.get("unit")
        metadata = metadata or values.get("metadata") or {}
        extra = {**{k: v for k, v in values.items() if k not in {
            "prediction_id", "id", "model_version_id", "location_id", "variable_code", "variable",
            "target_date", "generated_at", "horizon_days", "predicted_value", "value", "unit", "metadata"
        }}, **extra}
        if not all((model_version_id, location_id, variable, target_date)) or predicted_value is None:
            raise ValueError("model_version_id, location_id, variable, target_date, and predicted_value are required")
        code, _canonical, default_unit, _raw_unit = self.resolve_variable(str(variable))
        day = _date_string(target_date, "target_date")
        horizon_days = int(horizon_days)
        natural_key = f"{model_version_id}|{location_id}|{code}|{day}|{horizon_days}"
        prediction_id = str(prediction_id or hashlib.sha256(natural_key.encode()).hexdigest()[:32])
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO predictions(prediction_id, model_version_id, location_id, variable_code,
                   target_date, generated_at, horizon_days, predicted_value, unit, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(model_version_id, location_id, variable_code, target_date, horizon_days) DO UPDATE SET
                   generated_at=excluded.generated_at, predicted_value=excluded.predicted_value,
                   unit=excluded.unit, metadata_json=excluded.metadata_json""",
                (prediction_id, str(model_version_id), str(location_id), code, day, str(generated_at), horizon_days,
                 float(predicted_value), str(unit or default_unit), _json({**dict(metadata), **extra})),
            )
            row = self._connection.execute(
                """SELECT prediction_id FROM predictions WHERE model_version_id=? AND location_id=?
                   AND variable_code=? AND target_date=? AND horizon_days=?""",
                (str(model_version_id), str(location_id), code, day, horizon_days),
            ).fetchone()
        return row["prediction_id"]
