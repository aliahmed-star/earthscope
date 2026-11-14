"""GEOSTORM / EARTHSCOPE web API.

Thin FastAPI layer over dashboard_service.py (all application logic lives there).
Run: python -m uvicorn api:app --port 8000, then open http://localhost:8000
"""
import os
from datetime import date
from typing import Any, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import dashboard_service as svc
from earthscope.data_loader import DataLoadError
from earthscope.incidents import IncidentError
from earthscope.history_store import HistoryStore
from earthscope.prediction_model import (
    InsufficientDataError,
    load_model_metadata,
    predict_next_day,
)
from earthscope.climate_analysis import compare_locations
from earthscope.climate_model_suite import load_bundle as load_climate_bundle, predict_suite

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_ARCHIVE_QUERY_DAYS = 3660

app = FastAPI(title="GEOSTORM / EARTHSCOPE API")

# The main dashboard is served from this same origin, so it needs no CORS.
# A separate frontend may opt in to exact trusted origins using a comma-
# separated EARTHSCOPE_CORS_ORIGINS environment variable.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("EARTHSCOPE_CORS_ORIGINS", "").split(",")
    if origin.strip()
]
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )


class NoteBody(BaseModel):
    note: Optional[str] = None


@app.get("/api/status")
def api_status():
    return {"status": "online", "system": "GEOSTORM / EARTHSCOPE"}


@app.get("/api/stations")
def api_stations():
    return {"stations": svc.list_stations()}


@app.get("/api/dashboard")
def api_dashboard(
    mode: Literal["live", "demo", "historical"] = "live",
    stations: List[str] = Query(default=[]),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    try:
        return svc.build_dashboard(mode, stations, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except DataLoadError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/history/availability")
def api_history_availability():
    """Return only date coverage and record counts actually present in SQLite."""
    store = HistoryStore()
    try:
        return store.availability()
    finally:
        store.close()


@app.get("/api/climate/coverage")
def api_climate_coverage():
    """Country and exact per-variable calendar-year qualification from stored rows."""
    store = HistoryStore()
    try:
        availability = store.availability()
    finally:
        store.close()
    locations = availability.get("coverage", [])
    countries: dict[str, dict[str, Any]] = {}
    for location in locations:
        code = location.get("country_code") or location.get("location_id")
        country = countries.setdefault(code, {
            "country_name": location.get("country_name") or "Unspecified",
            "country_code": location.get("country_code") or "",
            "location_ids": [], "qualified": False, "common_complete_years": [],
        })
        country["location_ids"].append(location["location_id"])
        if location.get("qualified_10_complete_years"):
            country["qualified"] = True
            country["common_complete_years"] = location.get("common_complete_years", [])
    qualified = [item for item in countries.values() if item["qualified"]]
    return {
        "source": "NASA POWER Daily Point API (RE community, UTC)",
        "minimum_complete_years": 10,
        "qualification_rule": "At least ten shared full calendar years with every daily value valid for T2M, RH2M, WS10M, and PRECTOTCORR at the listed city coordinate.",
        "country_count": len(countries), "qualified_country_count": len(qualified),
        "countries": sorted(countries.values(), key=lambda item: item["country_name"]),
        "coverage": locations,
        "total_observation_rows": availability.get("total_observation_rows", 0),
        "latest_retrieved_at": availability.get("latest_retrieved_at"),
    }


@app.get("/api/climate/comparison")
def api_climate_comparison(
    locations: List[str] = Query(default=[]),
    start_date: date = Query(...),
    end_date: date = Query(...),
    variable: Literal["T2M", "RH2M", "WS10M", "PRECTOTCORR"] = "T2M",
):
    store = HistoryStore()
    try:
        return compare_locations(store, locations, start_date, end_date, variable, min_locations=2)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        store.close()


@app.get("/api/climate/trends")
def api_climate_trends(
    locations: List[str] = Query(default=[]),
    start_date: date = Query(default=date(1981, 1, 1)),
    end_date: date = Query(default=date(2025, 12, 31)),
    variable: Literal["T2M", "RH2M", "WS10M", "PRECTOTCORR"] = "T2M",
):
    store = HistoryStore()
    try:
        return compare_locations(store, locations, start_date, end_date, variable, min_locations=1)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        store.close()


@app.get("/api/climate/models/evaluation")
def api_climate_model_evaluation(
    variable: Optional[Literal["T2M", "RH2M", "WS10M", "PRECTOTCORR"]] = None,
    locations: List[str] = Query(default=[]),
):
    try:
        bundle = load_climate_bundle()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
    selected = set(locations)
    entries = []
    for item in bundle["entries"].values():
        metadata = item["metadata"]
        if selected and metadata.get("location_id") not in selected:
            continue
        if variable and metadata.get("variable_code") != variable:
            continue
        entries.append(metadata)
    return {"algorithm_version": bundle.get("algorithm_version"), "built_at": bundle.get("built_at"),
            "dataset": bundle.get("dataset"), "model_count": bundle.get("model_count"),
            "evaluations": entries, "caveats": bundle.get("caveats", [])}


@app.get("/api/predictions/next-day/all")
def api_all_next_day_estimates(locations: List[str] = Query(default=[])):
    try:
        return predict_suite(locations)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/history/observations")
def api_history_observations(
    location_id: str,
    variable: Literal["T2M", "RH2M", "WS10M", "PRECTOTCORR", "temperature_c", "humidity_pct", "wind_speed_kmh", "rainfall_mm"],
    start_date: date,
    end_date: date,
    resolution: Literal["daily"] = "daily",
    limit: int = Query(default=50000, ge=1, le=50000),
):
    if start_date > end_date:
        raise HTTPException(422, "start_date must be on or before end_date.")
    if (end_date - start_date).days + 1 > MAX_ARCHIVE_QUERY_DAYS:
        raise HTTPException(422, f"Historical observation queries are limited to {MAX_ARCHIVE_QUERY_DAYS} days.")
    known_locations = {item["location_id"] for item in svc.nasa_power.DEFAULT_LOCATIONS}
    if location_id not in known_locations:
        raise HTTPException(422, f"Unknown NASA POWER location: {location_id}.")
    store = HistoryStore()
    try:
        return store.query_observations(
            location_id, variable, start_date.isoformat(), end_date.isoformat(), resolution, limit
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        store.close()


@app.get("/api/graph-summaries")
def api_graph_summaries(
    mode: Literal["live", "demo", "historical"] = "historical",
    stations: List[str] = Query(default=[]),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    """Generate deterministic statistics from exactly the series the dashboard plots."""
    try:
        dashboard = svc.build_dashboard(mode, stations, start_date, end_date)
        return {
            "mode": dashboard["mode"],
            "range": dashboard["range"],
            "graph_summaries": dashboard["graph_summaries"],
        }
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except DataLoadError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/model/status")
def api_model_status():
    metadata = load_model_metadata()
    return {
        "available": metadata is not None,
        "model_version": metadata.get("model_version") if metadata else None,
        "location_id": metadata.get("location_id") if metadata else "cairo-eg",
        "target": metadata.get("variable") if metadata else "T2M",
        "training_command": "python scripts/train_temperature_model.py",
        "metadata": metadata,
    }


@app.get("/api/model/evaluation")
def api_model_evaluation():
    metadata = load_model_metadata()
    if metadata is None:
        raise HTTPException(404, "No trained model metadata is available; run the training script first.")
    return {
        "model_version": metadata.get("model_version"),
        "algorithm_version": metadata.get("algorithm_version"),
        "location_id": metadata.get("location_id"),
        "variable": metadata.get("variable"),
        "units": metadata.get("units"),
        "periods": metadata.get("periods"),
        "counts": metadata.get("counts"),
        "validation_metrics": metadata.get("validation_metrics"),
        "test_metrics": metadata.get("test_metrics"),
        "test_comparison_note": metadata.get("test_comparison_note"),
        "disclaimer": metadata.get("disclaimer"),
    }


@app.get("/api/predictions/next-day")
def api_next_day_prediction(location_id: Literal["cairo-eg"] = "cairo-eg"):
    try:
        return predict_next_day(location_id)
    except (FileNotFoundError, InsufficientDataError) as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/incidents")
def api_incidents(mode: Optional[Literal["live", "demo"]] = None):
    try:
        return {"incidents": svc.list_all_incidents(mode)}
    except IncidentError as exc:
        raise HTTPException(422, exc.message) from exc


@app.post("/api/incidents/{incident_id}/{action}")
def api_incident_action(
    incident_id: str,
    action: str,
    mode: Literal["live", "demo"] = "live",
    body: Optional[NoteBody] = None,
):
    """action = start | resolve | note (the dashboard buttons call this)."""
    try:
        return svc.incident_action(mode, incident_id, action, body.note if body else None)
    except IncidentError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 422
        raise HTTPException(status, exc.message) from exc


@app.get("/")
def index():
    path = os.path.join(HERE, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"message": "API is running successfully!"})
