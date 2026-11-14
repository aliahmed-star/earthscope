"""
test_analysis.py - tests for the GEOSTORM system logic (pytest).

Covers: observation validation, missing data, every risk level and threshold
boundary, normal conditions, the simulated severe-weather event, consistent
explanations, incident creation/retrieval, response-state transitions and
offline operation.

Run from the repository root with:  python -m pytest -v
"""

import copy
import socket
from datetime import datetime, timedelta, timezone

import pytest

from earthscope import config
from earthscope.analysis import assess_all, assess_observation, get_alerts
from earthscope.data_loader import (DataLoadError, ObservationValidationError,
                                    get_observations, load_demo_observations,
                                    validate_observation)
from earthscope.incidents import IncidentError, IncidentStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_raw(**overrides):
    """A valid, calm raw observation; tests override only what they need."""
    record = {
        "location_id": "test-1", "location_name": "Testville",
        "latitude": 10.0, "longitude": 20.0,
        "temperature_c": 20.0, "humidity_pct": 50.0, "wind_speed_kmh": 10.0, "rainfall_mm": 0.0,
        "observed_at": "2026-11-13T09:00:00Z", "data_source": "unit_test", "is_simulated": True,
    }
    record.update(overrides)
    return record


def assess(**overrides):
    return assess_observation(validate_observation(make_raw(**overrides)))


class FakeClock:
    """Predictable clock: each call moves one minute forward."""
    def __init__(self):
        self.now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.now += timedelta(minutes=1)
        return self.now


@pytest.fixture
def store():
    return IncidentStore(clock=FakeClock())


def critical_assessment(**overrides):
    return assess(location_id="storm-1", wind_speed_kmh=130.0, **overrides)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_valid_observation_is_normalised():
    obs = validate_observation(make_raw(observed_at="2026-11-13T11:00:00+02:00", temperature_c="21.5"))
    assert obs["observed_at"] == "2026-11-13T09:00:00Z"   # converted to UTC
    assert obs["temperature_c"] == 21.5                      # numeric string parsed


@pytest.mark.parametrize("field,value", [
    ("latitude", 90.1), ("latitude", -91), ("longitude", 180.5), ("longitude", -181),
    ("latitude", "north"), ("longitude", None),
])
def test_invalid_coordinates_rejected(field, value):
    with pytest.raises(ObservationValidationError) as exc:
        validate_observation(make_raw(**{field: value}))
    assert field in [e["field"] for e in exc.value.errors]


@pytest.mark.parametrize("field,value", [
    ("temperature_c", -90.1), ("temperature_c", 60.1), ("humidity_pct", -1), ("humidity_pct", 100.5),
    ("wind_speed_kmh", -5), ("wind_speed_kmh", 501), ("rainfall_mm", -0.1), ("rainfall_mm", 2001),
    ("temperature_c", "hot"), ("humidity_pct", float("nan")), ("wind_speed_kmh", True),
])
def test_invalid_measurements_rejected(field, value):
    with pytest.raises(ObservationValidationError) as exc:
        validate_observation(make_raw(**{field: value}))
    assert field in [e["field"] for e in exc.value.errors]


def test_range_edges_are_accepted():
    obs = validate_observation(make_raw(latitude=-90, longitude=180, humidity_pct=100, rainfall_mm=0))
    assert obs["humidity_pct"] == 100.0 and obs["rainfall_mm"] == 0.0


def test_missing_required_fields_reported_together():
    with pytest.raises(ObservationValidationError) as exc:
        validate_observation({"location_name": "x"})
    fields = {e["field"] for e in exc.value.errors}
    assert {"location_id", "latitude", "longitude", "observed_at", "is_simulated", "data_source"} <= fields


def test_timestamp_needs_timezone():
    with pytest.raises(ObservationValidationError):
        validate_observation(make_raw(observed_at="2026-11-13T09:00:00"))


def test_is_simulated_must_be_boolean():
    with pytest.raises(ObservationValidationError):
        validate_observation(make_raw(is_simulated="yes"))


def test_missing_measurement_stays_none_not_zero():
    obs = validate_observation(make_raw(wind_speed_kmh=None))
    assert obs["wind_speed_kmh"] is None


def test_non_dict_record_rejected():
    with pytest.raises(ObservationValidationError):
        validate_observation("not a dict")


# ---------------------------------------------------------------------------
# Risk levels and threshold boundaries (generated from the config)
# ---------------------------------------------------------------------------
SINGLE_FIELD_RULES = [r for r in config.HAZARD_RULES
                      if all(len(c) == 1 for c in r["levels"].values())]


def _hazard_level(assessment, hazard):
    for h in assessment["hazards"]:
        if h["hazard"] == hazard:
            return h["risk_level"]
    return None


@pytest.mark.parametrize("rule", SINGLE_FIELD_RULES, ids=lambda r: r["hazard"])
def test_every_level_boundary(rule):
    """At each threshold the level triggers (inclusive); just inside it does not."""
    ordered = [lvl for lvl in config.RISK_LEVELS if lvl in rule["levels"]]
    for index, level in enumerate(ordered):
        field, operator, threshold = rule["levels"][level][0]
        step = 0.1 if operator == ">=" else -0.1   # "just below" for >= ; "just above" for <=
        assert _hazard_level(assess(**{field: threshold}), rule["hazard"]) == level
        below = _hazard_level(assess(**{field: round(threshold - step, 1)}), rule["hazard"])
        assert below == (ordered[index - 1] if index else None)


def test_all_four_risk_levels_reachable():
    assert assess()["risk_level"] == "Low"
    assert assess(wind_speed_kmh=50.0)["risk_level"] == "Moderate"
    assert assess(wind_speed_kmh=90.0)["risk_level"] == "High"
    assert assess(wind_speed_kmh=120.0)["risk_level"] == "Critical"


def test_alert_flag_matches_threshold_level():
    assert assess()["alert"] is False
    assert assess(wind_speed_kmh=50.0)["alert"] is True


def test_wildfire_requires_all_conditions():
    base = dict(temperature_c=36.0, humidity_pct=18.0, wind_speed_kmh=45.0)
    assert _hazard_level(assess(**base), config.HAZARD_WILDFIRE) == "High"
    # Break one condition at a time: the High level must disappear.
    assert _hazard_level(assess(**{**base, "humidity_pct": 21.0}), config.HAZARD_WILDFIRE) == "Moderate"
    assert _hazard_level(assess(**{**base, "wind_speed_kmh": 39.9}), config.HAZARD_WILDFIRE) == "Moderate"
    assert _hazard_level(assess(**{**base, "temperature_c": 29.9}), config.HAZARD_WILDFIRE) is None


def test_highest_hazard_wins_and_ties_use_rule_order():
    result = assess(wind_speed_kmh=130.0, rainfall_mm=160.0)   # both Critical
    assert result["risk_level"] == "Critical"
    assert result["primary_hazard"] == config.HAZARD_WIND       # Wind is listed before Rain
    assert [h["hazard"] for h in result["hazards"]] == [config.HAZARD_WIND, config.HAZARD_RAIN]


# ---------------------------------------------------------------------------
# Normal conditions, missing data and limitations
# ---------------------------------------------------------------------------
def test_normal_conditions_have_no_alert():
    result = assess()
    assert result["risk_level"] == "Low" and result["alert"] is False
    assert result["primary_hazard"] == config.HAZARD_NONE and result["hazards"] == []
    assert result["supporting_measurements"] == {}


def test_missing_measurement_reported_and_never_invents_hazard():
    result = assess(wind_speed_kmh=None)
    assert result["missing_measurements"] == ["wind_speed_kmh"]
    assert result["risk_level"] == "Low"
    assert any("Wind speed" in text for text in result["limitations"])
    assert any(config.HAZARD_WIND in text and "could not be fully evaluated" in text
               for text in result["limitations"])


def test_missing_data_can_still_flag_hazard_from_available_data():
    result = assess(temperature_c=47.0, humidity_pct=None, wind_speed_kmh=None, rainfall_mm=None)
    assert result["risk_level"] == "Critical" and result["primary_hazard"] == config.HAZARD_HEAT


def test_no_measurements_means_insufficient_data():
    result = assess(temperature_c=None, humidity_pct=None, wind_speed_kmh=None, rainfall_mm=None)
    assert result["status"] == "insufficient_data"
    assert result["risk_level"] is None and result["alert"] is False


def test_simulated_flag_preserved_and_labelled():
    simulated = assess(is_simulated=True)
    live = assess(is_simulated=False)
    assert simulated["is_simulated"] is True and live["is_simulated"] is False
    assert any("simulated" in text.lower() for text in simulated["limitations"])
    assert not any("simulated" in text.lower() for text in live["limitations"])


def test_assessment_is_deterministic():
    obs = validate_observation(make_raw(wind_speed_kmh=95.0, rainfall_mm=120.0))
    assert assess_observation(obs) == assess_observation(copy.deepcopy(obs))


def test_explanation_mentions_value_threshold_and_hazard():
    result = assess(wind_speed_kmh=95.0)
    text = " ".join(result["reasons"])
    assert result["primary_hazard"] == config.HAZARD_WIND and result["risk_level"] == "High"
    assert "95" in text and "90" in text and "Wind speed" in text and "High" in text
    assert result["supporting_measurements"] == {"wind_speed_kmh": 95.0}


def test_assessment_contains_disclaimer():
    assert "not official" in assess()["disclaimer"]


# ---------------------------------------------------------------------------
# Demo dataset and the simulated severe-weather event
# ---------------------------------------------------------------------------
def test_demo_dataset_loads_with_distinct_locations():
    observations, rejected = load_demo_observations()
    assert rejected == []
    assert len(observations) >= 3
    assert len({o["location_id"] for o in observations}) == len(observations)
    assert all(o["is_simulated"] for o in observations)


def test_simulated_severe_event_reliably_alerts():
    observations, _ = load_demo_observations()
    manila = next(a for a in assess_all(observations) if a["location_id"] == "manila-ph")
    assert manila["risk_level"] == "Critical" and manila["alert"] is True
    assert manila["primary_hazard"] == config.HAZARD_WIND
    assert {h["hazard"] for h in manila["hazards"]} == {config.HAZARD_WIND, config.HAZARD_RAIN}
    assert manila["is_simulated"] is True


def test_expected_demo_outcomes():
    expected = {"cairo-eg": "Low", "reykjavik-is": "Low", "tokyo-jp": "Low", "manila-ph": "Critical",
                "phoenix-us": "High", "sydney-au": "High", "nairobi-ke": "Low"}
    observations, _ = load_demo_observations()
    actual = {a["location_id"]: a["risk_level"] for a in assess_all(observations)}
    assert actual == expected
    sydney = next(a for a in assess_all(observations) if a["location_id"] == "sydney-au")
    assert sydney["primary_hazard"] == config.HAZARD_WILDFIRE


def test_get_alerts_sorted_most_severe_first():
    observations, _ = load_demo_observations()
    alerts = get_alerts(assess_all(observations))
    assert [a["location_id"] for a in alerts] == ["manila-ph", "phoenix-us", "sydney-au"]


def test_nairobi_demo_reports_missing_wind():
    observations, _ = load_demo_observations()
    nairobi = next(a for a in assess_all(observations) if a["location_id"] == "nairobi-ke")
    assert nairobi["missing_measurements"] == ["wind_speed_kmh"]


# ---------------------------------------------------------------------------
# Offline operation and fallback
# ---------------------------------------------------------------------------
def test_full_pipeline_works_with_network_blocked(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)

    loaded = get_observations()
    assert loaded["mode"] == "demo"
    store = IncidentStore()
    results = store.register_alerts(assess_all(loaded["observations"]))
    assert len(results) == 3 and all(r["created"] for r in results)


def test_failing_provider_falls_back_to_demo():
    def broken():
        raise ConnectionError("no internet")
    loaded = get_observations(provider=broken)
    assert loaded["mode"] == "demo" and len(loaded["observations"]) >= 3
    assert any("failed" in note for note in loaded["notes"])


def test_provider_with_only_invalid_data_falls_back():
    loaded = get_observations(provider=lambda: [{"bad": "record"}])
    assert loaded["mode"] == "demo"


def test_working_provider_is_labelled_live():
    live = make_raw(location_id="live-1", is_simulated=False, data_source="fake_provider")
    loaded = get_observations(provider=lambda: [live, {"bad": 1}])
    assert loaded["mode"] == "live"
    assert [o["location_id"] for o in loaded["observations"]] == ["live-1"]
    assert loaded["observations"][0]["is_simulated"] is False
    assert len(loaded["rejected"]) == 1


def test_missing_demo_file_raises_clear_error(tmp_path):
    with pytest.raises(DataLoadError):
        load_demo_observations(tmp_path / "nope.json")


def test_malformed_demo_file_raises_clear_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(DataLoadError):
        load_demo_observations(bad)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------
def test_create_and_retrieve_incident(store):
    result = store.register_from_assessment(critical_assessment())
    assert result["created"] is True
    incident = store.get_incident(result["incident"]["incident_id"])
    assert incident["incident_id"] == "INC-0001"
    assert incident["status"] == config.STATUS_PENDING
    assert incident["hazard_type"] == config.HAZARD_WIND and incident["risk_level"] == "Critical"
    assert incident["supporting_measurements"] == {"wind_speed_kmh": 130.0}
    assert incident["risk_explanation"] and incident["detected_at"].endswith("Z")
    assert incident["operator_notes"] == []


def test_non_alert_cannot_become_incident(store):
    with pytest.raises(IncidentError) as exc:
        store.register_from_assessment(assess())
    assert exc.value.code == "NOT_AN_ALERT"


def test_incomplete_assessment_rejected(store):
    with pytest.raises(IncidentError) as exc:
        store.register_from_assessment({"alert": True})
    assert exc.value.code == "INVALID_ASSESSMENT"


def test_refresh_does_not_duplicate_incidents(store):
    first = store.register_from_assessment(critical_assessment())
    second = store.register_from_assessment(critical_assessment())
    assert first["created"] and not second["created"] and not second["updated"]
    assert len(store.list_incidents()) == 1


def test_active_incident_updates_when_risk_changes(store):
    store.register_from_assessment(assess(location_id="storm-1", wind_speed_kmh=95.0))
    result = store.register_from_assessment(assess(location_id="storm-1", wind_speed_kmh=125.0))
    assert result["updated"] and not result["created"]
    assert result["incident"]["risk_level"] == "Critical"
    assert len(store.list_incidents()) == 1


def test_resolved_event_not_reopened_by_refresh(store):
    incident_id = store.register_from_assessment(critical_assessment())["incident"]["incident_id"]
    store.start_response(incident_id)
    store.resolve_incident(incident_id)
    again = store.register_from_assessment(critical_assessment())
    assert again["created"] is False
    assert len(store.list_incidents()) == 1


def test_new_observation_after_resolution_creates_new_incident(store):
    incident_id = store.register_from_assessment(critical_assessment())["incident"]["incident_id"]
    store.start_response(incident_id)
    store.resolve_incident(incident_id)
    later = critical_assessment(observed_at="2026-11-13T15:00:00Z")
    assert store.register_from_assessment(later)["created"] is True


def test_valid_transition_sequence_records_history_and_notes(store):
    incident_id = store.register_from_assessment(critical_assessment())["incident"]["incident_id"]
    started = store.start_response(incident_id, operator_note="Team notified")
    assert started["status"] == config.STATUS_IN_PROGRESS
    resolved = store.resolve_incident(incident_id, operator_note="All clear")
    assert resolved["status"] == config.STATUS_RESOLVED
    assert [h["status"] for h in resolved["status_history"]] == list(config.RESPONSE_STATUSES)
    assert [n["text"] for n in resolved["operator_notes"]] == ["Team notified", "All clear"]


def test_cannot_resolve_pending_incident(store):
    incident_id = store.register_from_assessment(critical_assessment())["incident"]["incident_id"]
    with pytest.raises(IncidentError) as exc:
        store.resolve_incident(incident_id)
    assert exc.value.code == "INVALID_TRANSITION" and "In Progress" in exc.value.message
    assert store.get_incident(incident_id)["status"] == config.STATUS_PENDING


def test_cannot_start_twice_or_change_resolved(store):
    incident_id = store.register_from_assessment(critical_assessment())["incident"]["incident_id"]
    store.start_response(incident_id)
    with pytest.raises(IncidentError) as exc:
        store.start_response(incident_id)
    assert exc.value.code == "INVALID_TRANSITION"
    store.resolve_incident(incident_id)
    for action in (store.start_response, store.resolve_incident):
        with pytest.raises(IncidentError) as exc:
            action(incident_id)
        assert exc.value.code == "INVALID_TRANSITION" and "already resolved" in exc.value.message


def test_unknown_incident_raises_not_found(store):
    for action in (store.get_incident, store.start_response, store.resolve_incident):
        with pytest.raises(IncidentError) as exc:
            action("INC-9999")
        assert exc.value.code == "NOT_FOUND"


def test_list_filters_and_ordering(store):
    store.register_from_assessment(assess(location_id="a", wind_speed_kmh=95.0))    # High
    store.register_from_assessment(assess(location_id="b", wind_speed_kmh=130.0))   # Critical
    listing = store.list_incidents()
    assert [i["location_id"] for i in listing] == ["b", "a"]
    store.start_response(listing[0]["incident_id"])
    assert [i["location_id"] for i in store.list_incidents(status=config.STATUS_IN_PROGRESS)] == ["b"]
    assert [i["location_id"] for i in store.list_incidents(location_id="a")] == ["a"]
    with pytest.raises(IncidentError):
        store.list_incidents(status="Bogus")


def test_returned_incidents_are_copies(store):
    incident_id = store.register_from_assessment(critical_assessment())["incident"]["incident_id"]
    store.get_incident(incident_id)["status"] = "Resolved"   # mutate the copy
    assert store.get_incident(incident_id)["status"] == config.STATUS_PENDING


def test_demo_end_to_end_flow(store):
    """The core demo: load -> assess -> alert -> incident -> respond -> resolve."""
    observations = get_observations()["observations"]
    assessments = assess_all(observations)
    store.register_alerts(assessments)
    top = store.list_incidents()[0]
    assert top["location_id"] == "manila-ph" and top["risk_level"] == "Critical"
    store.start_response(top["incident_id"])
    assert store.resolve_incident(top["incident_id"])["status"] == config.STATUS_RESOLVED
    store.register_alerts(assessments)   # a dashboard refresh must not reopen it
    assert len(store.list_incidents()) == 3


def test_persistence_round_trip(tmp_path):
    path = tmp_path / "incidents.json"
    first = IncidentStore(path=path, clock=FakeClock())
    incident_id = first.register_from_assessment(critical_assessment())["incident"]["incident_id"]
    first.start_response(incident_id)
    second = IncidentStore(path=path)
    assert second.get_incident(incident_id)["status"] == config.STATUS_IN_PROGRESS
    # The counter is restored, so new IDs do not collide.
    assert second.register_from_assessment(assess(location_id="other", wind_speed_kmh=100.0))["incident"]["incident_id"] == "INC-0002"


def test_corrupt_persistence_file_does_not_crash(tmp_path):
    path = tmp_path / "incidents.json"
    path.write_text("garbage")
    assert IncidentStore(path=path).list_incidents() == []
