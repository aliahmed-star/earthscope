"""API tests for the merged dashboard (incident routes the web page's buttons call)."""
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import api  # noqa: E402
from earthscope.history_store import HistoryStore  # noqa: E402

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


def test_climate_coverage_endpoint_exposes_country_and_exact_qualification_rule(tmp_path, monkeypatch):
    database = tmp_path / "coverage-api.sqlite3"
    monkeypatch.setattr(api, "HistoryStore", lambda: HistoryStore(database))
    response = client.get("/api/climate/coverage")
    assert response.status_code == 200
    payload = response.json()
    assert payload["minimum_complete_years"] == 10
    assert "shared full calendar years" in payload["qualification_rule"]
    assert payload["country_count"] >= 10
    assert payload["qualified_country_count"] == 0
    assert {item["country_code"] for item in payload["countries"]} >= {"EG", "US", "JP", "AU", "PH"}


def test_comparison_and_trend_routes_use_shared_dates_and_warn_about_missing_values(tmp_path, monkeypatch):
    database = tmp_path / "comparison-api.sqlite3"
    store = HistoryStore(database)
    for code, country, lat in (("api-a", "APIland A", 5.0), ("api-b", "APIland B", -5.0)):
        store.register_location({"location_id": code, "location_name": code.upper(), "country_name": country,
                                 "country_code": code[-1].upper(), "latitude": lat, "longitude": 10.0})
        value = 20.0 if code == "api-a" else 30.0
        store.upsert_observations([{
            "location_id": code, "variable_code": "T2M", "observed_on": day,
            "raw_value": value, "raw_unit": "°C", "normalized_value": value, "canonical_unit": "°C",
            "source_metadata": {"fixture": "api-route-test"},
        } for day in ("2020-01-01", "2020-01-02")])
    store.close()
    monkeypatch.setattr(api, "HistoryStore", lambda: HistoryStore(database))

    params = [("locations", "api-a"), ("locations", "api-b"),
              ("start_date", "2020-01-01"), ("end_date", "2020-12-31"), ("variable", "T2M")]
    response = client.get("/api/climate/comparison", params=params)
    assert response.status_code == 200
    payload = response.json()
    assert payload["range"] == {"start": "2020-01-01", "end": "2020-12-31"}
    assert payload["ranked_location_ids"] == ["api-b", "api-a"]
    assert payload["locations"][0]["maximum_daily"]["date"] == "2020-01-01"
    assert any("none were filled" in warning for warning in payload["locations"][0]["warnings"])

    trend = client.get("/api/climate/trends", params=[("locations", "api-a"),
                         ("start_date", "2020-01-01"), ("end_date", "2020-12-31"), ("variable", "T2M")])
    assert trend.status_code == 200
    assert trend.json()["locations"][0]["trend"]["status"] == "insufficient_complete_years"


def test_climate_model_evaluation_filters_and_estimates_are_parameterized(monkeypatch):
    sample = {"algorithm_version": "test-v1", "built_at": "2026-01-01T00:00:00Z", "model_count": 2,
              "dataset": "NASA POWER Daily", "caveats": ["Not a forecast"],
              "entries": {
                  "a": {"metadata": {"location_id": "cairo-eg", "variable_code": "T2M", "status": "evaluated"}},
                  "b": {"metadata": {"location_id": "nairobi-ke", "variable_code": "RH2M", "status": "evaluated"}},
              }}
    monkeypatch.setattr(api, "load_climate_bundle", lambda: sample)
    response = client.get("/api/climate/models/evaluation", params={"locations": "cairo-eg", "variable": "T2M"})
    assert response.status_code == 200
    assert [item["location_id"] for item in response.json()["evaluations"]] == ["cairo-eg"]

    calls = []
    monkeypatch.setattr(api, "predict_suite", lambda locations: calls.append(locations) or {"predictions": []})
    estimates = client.get("/api/predictions/next-day/all", params=[("locations", "cairo-eg"), ("locations", "toronto-ca")])
    assert estimates.status_code == 200
    assert calls == [["cairo-eg", "toronto-ca"]]
