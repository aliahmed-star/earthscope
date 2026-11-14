"""
test_integration.py - Integration and end-to-end tests for EARTHSCOPE / GEOSTORM Phase 3.

Verifies:
1. Full end-to-end data pipeline: data_loader -> analysis -> incidents.
2. Component compatibility with real system-logic data structures (df_incidents, df_obs).
3. charts.py chart generation.
4. Globe layer creation and PyDeck serialization.
5. Error handling and incident workflow transitions.
"""
import pytest
import pandas as pd
from earthscope import config
from earthscope.data_loader import get_observations
from earthscope.analysis import assess_all, get_alerts
from earthscope.incidents import get_default_store, IncidentStore, IncidentError
from earthscope.charts import create_trend_chart
from components.globe import build_globe


def test_full_pipeline_demo_data():
    """Verify demo data loads, assesses, and registers incidents cleanly."""
    obs_res = get_observations()
    assert obs_res["mode"] == "demo"
    assert len(obs_res["observations"]) == 7
    assert len(obs_res["rejected"]) == 0

    assessments = assess_all(obs_res["observations"])
    assert len(assessments) == 7

    alerts = get_alerts(assessments)
    # Manila (Critical), Phoenix (High), Sydney (High)
    assert len(alerts) == 3
    hazard_types = {a["primary_hazard"] for a in alerts}
    assert "Severe Wind" in hazard_types
    assert "Extreme Heat" in hazard_types
    assert "Wildfire Conditions" in hazard_types

    store = IncidentStore()
    registered = store.register_alerts(assessments)
    assert len(registered) == 3

    incidents = store.list_incidents()
    assert len(incidents) == 3
    # Check severity ordering (Critical first)
    assert incidents[0]["risk_level"] == "Critical"
    assert incidents[0]["location_id"] == "manila-ph"


def test_incident_response_transitions():
    """Verify state transitions and transition validation."""
    store = IncidentStore()
    obs_res = get_observations()
    store.register_alerts(assess_all(obs_res["observations"]))

    inc = store.list_incidents()[0]
    inc_id = inc["incident_id"]
    assert inc["status"] == config.STATUS_PENDING

    # Disallowed: Pending -> Resolved
    with pytest.raises(IncidentError) as exc_info:
        store.resolve_incident(inc_id)
    assert exc_info.value.code == "INVALID_TRANSITION"

    # Allowed: Pending -> In Progress
    updated = store.start_response(inc_id, operator_note="Testing start")
    assert updated["status"] == config.STATUS_IN_PROGRESS

    # Allowed: In Progress -> Resolved
    resolved = store.resolve_incident(inc_id, operator_note="Testing resolution")
    assert resolved["status"] == config.STATUS_RESOLVED


def test_globe_builder_with_real_incidents():
    """Verify PyDeck globe is constructed from real incident DataFrame without errors."""
    store = IncidentStore()
    store.register_alerts(assess_all(get_observations()["observations"]))
    df_incidents = pd.DataFrame(store.list_incidents())

    deck = build_globe(df_incidents)
    assert deck is not None
    assert len(deck.layers) == 1
    assert deck.layers[0].type == "ScatterplotLayer"

    # Test empty DataFrame case
    empty_deck = build_globe(pd.DataFrame())
    assert empty_deck is not None
    assert len(empty_deck.layers) == 0


def test_charts_creation_with_real_observations():
    """Verify create_trend_chart generates valid Plotly figures for observed locations."""
    obs_res = get_observations()
    df_obs = pd.DataFrame(obs_res["observations"])

    # Test with valid location
    fig = create_trend_chart(df_obs, "Manila, Philippines")
    assert fig is not None
    assert len(fig.data) >= 3  # temp, humidity, wind, rain

    # Test with empty DataFrame
    fig_empty = create_trend_chart(pd.DataFrame(), "Unknown")
    assert fig_empty is None
