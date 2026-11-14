"""
incidents.py - incident registry and simulated response workflow.

WHY THIS IS A NEW FILE
    The agreed structure has no place for incident state. Keeping it here means
    there is exactly ONE copy of the incident logic; the frontend only calls
    these functions and never re-implements state transitions.

RESPONSIBILITY
    * Turn an alert-level assessment (analysis.py) into an incident.
    * Avoid duplicates when the dashboard refreshes with unchanged data.
    * Move an incident through  Pending -> In Progress -> Resolved  and reject
      any other transition with a useful error.
    * Keep operator notes and a status history.

STORAGE
    In memory by default (simplest and most reliable for a demo). If
    config.PERSIST_INCIDENTS is True (or a path is passed to IncidentStore)
    every change is also saved to a JSON file so incidents survive a restart.

THIS IS A SIMULATION
    "Starting a response" only changes a status field. Nothing here dispatches
    real emergency services or controls any real equipment.

DE-DUPLICATION RULES (register_from_assessment)
    * Same location + hazard already has an ACTIVE (Pending/In Progress)
      incident -> no new incident. If the risk or measurements changed, the
      existing incident is updated in place.
    * An incident for the same location + hazard + observation time was
      already RESOLVED -> nothing is created (a refresh must not reopen it).
    * Otherwise a new incident is created.
"""

import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import config


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class IncidentError(Exception):
    """Raised for any incident problem. `code` is machine-readable, `message` is for people.

    Codes: NOT_FOUND, INVALID_TRANSITION, NOT_AN_ALERT, INVALID_ASSESSMENT.
    """

    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self):
        return {"ok": False, "error": {"code": self.code, "message": self.message}}


def _utc_now():
    return datetime.now(timezone.utc)


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------
class IncidentStore:
    """Holds all incidents and enforces the response workflow.

    path:  optional JSON file for persistence (None = memory only).
    clock: optional zero-argument function returning an aware datetime; tests
           pass a fake clock so timestamps are predictable.
    """

    def __init__(self, path=None, clock=None):
        self._path = Path(path) if path else None
        self._clock = clock or _utc_now
        self._incidents = {}      # incident_id -> incident dict
        self._counter = 0         # used to build INC-0001, INC-0002, ...
        if self._path and self._path.exists():
            self._load()

    # ----- persistence -------------------------------------------------------
    def _load(self):
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._incidents = {i["incident_id"]: i for i in data["incidents"]}
            self._counter = int(data["counter"])
        except (OSError, ValueError, KeyError, TypeError):
            # A corrupt file must not crash the dashboard; start clean instead.
            self._incidents, self._counter = {}, 0

    def _save(self):
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"counter": self._counter, "incidents": list(self._incidents.values())}, indent=2)
        # Write to a temp file then rename, so a crash never leaves half a file.
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp, self._path)

    def _now(self):
        return _iso(self._clock())

    # ----- internal lookups ---------------------------------------------------
    def _require(self, incident_id):
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise IncidentError("NOT_FOUND", f"Incident {incident_id!r} does not exist.")
        return incident

    def _find_active(self, location_id, hazard):
        for incident in self._incidents.values():
            if (incident["location_id"] == location_id and incident["hazard_type"] == hazard
                    and incident["status"] != config.STATUS_RESOLVED):
                return incident
        return None

    def _find_resolved_same_event(self, location_id, hazard, observed_at):
        for incident in self._incidents.values():
            if (incident["location_id"] == location_id and incident["hazard_type"] == hazard
                    and incident["observed_at"] == observed_at
                    and incident["status"] == config.STATUS_RESOLVED):
                return incident
        return None

    # ----- registering ----------------------------------------------------------
    def register_from_assessment(self, assessment):
        """Create (or update) an incident from an analysis.assess_observation() result.

        Returns {"incident": dict|None, "created": bool, "updated": bool, "reason": str}.
        Raises IncidentError(NOT_AN_ALERT) when assessment["alert"] is not True, and
        IncidentError(INVALID_ASSESSMENT) when the assessment lacks required keys.
        """
        required = ("location_id", "primary_hazard", "risk_level", "alert", "observed_at")
        if not isinstance(assessment, dict) or any(key not in assessment for key in required):
            raise IncidentError("INVALID_ASSESSMENT", "Assessment is missing required fields.")
        if not assessment["alert"]:
            raise IncidentError("NOT_AN_ALERT", "Only alert-level assessments can become incidents.")

        location_id, hazard = assessment["location_id"], assessment["primary_hazard"]
        observed_at = assessment["observed_at"]

        # Event details that may change when the same incident is re-assessed.
        details = {
            "risk_level": assessment["risk_level"],
            "supporting_measurements": copy.deepcopy(assessment.get("supporting_measurements", {})),
            "risk_explanation": list(assessment.get("reasons", [])),
            "observed_at": observed_at,
        }

        active = self._find_active(location_id, hazard)
        if active:
            changed = any(active[key] != value for key, value in details.items())
            if not changed:
                return {"incident": copy.deepcopy(active), "created": False, "updated": False,
                        "reason": "Existing active incident is unchanged."}
            active.update(details)
            active["updated_at"] = self._now()
            self._save()
            return {"incident": copy.deepcopy(active), "created": False, "updated": True,
                    "reason": "Existing active incident updated with newer assessment."}

        resolved = self._find_resolved_same_event(location_id, hazard, observed_at)
        if resolved:
            return {"incident": copy.deepcopy(resolved), "created": False, "updated": False,
                    "reason": "This event was already resolved; not reopened."}

        # --- brand-new incident ------------------------------------------------
        self._counter += 1
        now = self._now()
        incident = {
            "incident_id": f"INC-{self._counter:04d}",
            "location_id": location_id,
            "location_name": assessment.get("location_name"),
            "latitude": assessment.get("latitude"),
            "longitude": assessment.get("longitude"),
            "hazard_type": hazard,
            "data_source": assessment.get("data_source"),
            "is_simulated": assessment.get("is_simulated"),
            "detected_at": now,
            "updated_at": now,
            "status": config.STATUS_PENDING,
            "status_history": [{"status": config.STATUS_PENDING, "at": now}],
            "operator_notes": [],
            **details,
        }
        self._incidents[incident["incident_id"]] = incident
        self._save()
        return {"incident": copy.deepcopy(incident), "created": True, "updated": False,
                "reason": "New incident created."}

    def register_alerts(self, assessments):
        """Register every alert in a list of assessments; non-alerts are skipped.

        Convenient for a dashboard refresh. Returns the list of result dicts
        from register_from_assessment().
        """
        return [self.register_from_assessment(a) for a in assessments if a.get("alert")]

    # ----- reading ----------------------------------------------------------------
    def list_incidents(self, status=None, location_id=None):
        """Return incidents (copies), most severe first, then by ID.

        status:      optional filter, one of config.RESPONSE_STATUSES.
        location_id: optional filter.
        Raises IncidentError(INVALID_ASSESSMENT) if `status` is not a known status.
        """
        if status is not None and status not in config.RESPONSE_STATUSES:
            raise IncidentError("INVALID_ASSESSMENT", f"Unknown status filter {status!r}.")
        items = [i for i in self._incidents.values()
                 if (status is None or i["status"] == status)
                 and (location_id is None or i["location_id"] == location_id)]
        items.sort(key=lambda i: (-config.RISK_RANK[i["risk_level"]], i["incident_id"]))
        return copy.deepcopy(items)

    def get_incident(self, incident_id):
        """Return a copy of one incident or raise IncidentError(NOT_FOUND)."""
        return copy.deepcopy(self._require(incident_id))

    # ----- workflow ------------------------------------------------------------------
    def _transition(self, incident_id, new_status, operator_note):
        incident = self._require(incident_id)
        allowed = config.ALLOWED_TRANSITIONS[incident["status"]]
        if new_status not in allowed:
            hint = (f"Allowed next status: {', '.join(allowed)}." if allowed
                    else "This incident is already resolved and cannot change.")
            raise IncidentError(
                "INVALID_TRANSITION",
                f"Cannot move {incident_id} from '{incident['status']}' to '{new_status}'. {hint}")
        now = self._now()
        incident["status"] = new_status
        incident["updated_at"] = now
        incident["status_history"].append({"status": new_status, "at": now})
        if operator_note:
            incident["operator_notes"].append({"at": now, "text": str(operator_note)})
        self._save()
        return copy.deepcopy(incident)

    def start_response(self, incident_id, operator_note=None):
        """Pending -> In Progress. Returns the updated incident copy."""
        return self._transition(incident_id, config.STATUS_IN_PROGRESS, operator_note)

    def resolve_incident(self, incident_id, operator_note=None):
        """In Progress -> Resolved. Returns the updated incident copy."""
        return self._transition(incident_id, config.STATUS_RESOLVED, operator_note)

    def add_note(self, incident_id, text):
        """Attach an operator note without changing the status."""
        if not isinstance(text, str) or not text.strip():
            raise IncidentError("INVALID_ASSESSMENT", "Note text must be non-empty.")
        incident = self._require(incident_id)
        now = self._now()
        incident["operator_notes"].append({"at": now, "text": text.strip()})
        incident["updated_at"] = now
        self._save()
        return copy.deepcopy(incident)

    def reset(self):
        """Delete all incidents (used to restart a demonstration)."""
        self._incidents, self._counter = {}, 0
        self._save()


# ---------------------------------------------------------------------------
# Shared store for the running application
# ---------------------------------------------------------------------------
_default_store = None


def get_default_store():
    """Return the single IncidentStore shared by the whole app.

    Python keeps module-level variables alive between dashboard refreshes, so
    every part of the app sees the same incidents. (If the frontend framework
    reloads modules on each run, store this object in the framework's session
    state instead - see docs/architecture.md.)
    """
    global _default_store
    if _default_store is None:
        _default_store = IncidentStore(path=config.INCIDENT_STORE_PATH if config.PERSIST_INCIDENTS else None)
    return _default_store
