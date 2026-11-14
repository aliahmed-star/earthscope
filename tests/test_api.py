"""API tests for the merged dashboard (incident routes the web page's buttons call)."""
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import api  # noqa: E402

client = TestClient(api.app)


def _demo():
    return client.get("/api/dashboard", params={"mode": "demo"}).json()


def test_status_and_stations():
    assert client.get("/api/status").json()["status"] == "online"
    assert len(client.get("/api/stations").json()["stations"]) >= 7


def test_demo_location_filter_and_invalid_parameters():
    response = client.get("/api/dashboard", params={"mode": "demo", "stations": "manila-ph"})
    assert response.status_code == 200
    assert [station["id"] for station in response.json()["stations"]] == ["manila-ph"]
    assert client.get("/api/dashboard", params={"mode": "unknown"}).status_code == 422
    response = client.get("/api/dashboard", params={"mode": "live", "stations": "unknown-location"})
    assert response.status_code == 422


def test_incidents_endpoint_returns_documented_wrapped_list():
    response = client.get("/api/incidents", params={"mode": "demo"})
    assert response.status_code == 200
    assert isinstance(response.json().get("incidents"), list)


def test_cors_is_not_wildcard_by_default():
    if not api.CORS_ORIGINS:
        response = client.get("/api/status", headers={"Origin": "https://untrusted.example"})
        assert "access-control-allow-origin" not in response.headers


def test_demo_dashboard_shape():
    d = _demo()
    assert d["mode"] == "demo" and d["is_simulated"] is True
    assert len(d["stations"]) == 7 and set(d["series"]) == {s["id"] for s in d["stations"]}
    assert {s["name"]: s["risk_level"] for s in d["stations"]}["Manila, Philippines"] == "Critical"


def test_incident_buttons_workflow():
    inc = _demo()["incidents"][0]
    iid = inc["incident_id"]
    r = client.post(f"/api/incidents/{iid}/start?mode=demo", json={"note": "crew sent"})
    assert r.status_code == 200 and r.json()["status"] == "In Progress"
    r = client.post(f"/api/incidents/{iid}/note?mode=demo", json={"note": "hello"})
    assert r.json()["operator_notes"][-1]["text"] == "hello"
    r = client.post(f"/api/incidents/{iid}/resolve?mode=demo", json={})
    assert r.json()["status"] == "Resolved"


def test_incident_errors():
    assert client.post("/api/incidents/NOPE/start?mode=demo", json={}).status_code == 404
    iid = _demo()["incidents"][1]["incident_id"]
    client.post(f"/api/incidents/{iid}/start?mode=demo", json={})
    client.post(f"/api/incidents/{iid}/resolve?mode=demo", json={})
    assert client.post(f"/api/incidents/{iid}/start?mode=demo", json={}).status_code == 422


def test_page_uses_deck_map_not_leaflet():
    html = client.get("/").text
    assert "deck.DeckGL" in html and "leaflet" not in html.lower()
