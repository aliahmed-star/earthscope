# EarthScope / GEOSTORM architecture

## Current application flow

The primary application is a browser-based dashboard served at `/` by FastAPI (`api.py`). The static `index.html` calls the same-origin API and renders the selected locations, measurements, time-series charts, and incidents. The map and graphs consume one `/api/dashboard` response so they use the same location/date selection and the same data mode.

The dashboard data flow is:

```text
Browser controls
  -> GET /api/dashboard
  -> dashboard_service.build_dashboard
  -> NASA POWER Daily point API (UTC)
  -> normalize_nasa_power_records
  -> data_loader.validate_many
  -> analysis.assess_observation
  -> incidents.IncidentStore
  -> aligned, JSON-safe map/table/chart payload
```

If a live request fails or returns no valid records, the existing data loader supplies `data/processed/demo_observations.json`. The response keeps `mode`, `requested_mode`, `is_simulated`, notes, and source metadata separate so the UI can label the fallback. A request that has partial results may display those results with a note about failed locations. Explicitly selected locations remain filtered even when the fallback is used.

## Modules

- `api.py`: FastAPI routes for status, locations, live/demo/historical dashboard data, archive queries, graph summaries, model evaluation and predictions, incidents, and incident actions. Same-origin use is the default; cross-origin access is opt-in through `EARTHSCOPE_CORS_ORIGINS`.
- `dashboard_service.py`: coordinate selection, separate live/historical date bounds, parallel point requests (up to five workers), ten-minute in-memory live-response cache capped at 128 entries, daily chart-series alignment, assessments, summaries, and per-mode incident stores.
- `src/earthscope/providers/nasa_power.py`: NASA POWER HTTP client, UTC request parameter, bounded timeout, fill/non-finite handling, daily observation normalization, unit conversion, and preservation of response metadata.
- `src/earthscope/data_loader.py`: shared schema validation, coordinate/value range checks, timezone normalization, missing-value handling, source-metadata filtering, and explicit offline fallback.
- `src/earthscope/analysis.py`: deterministic rule-based assessments and explanations. Missing measurements are not treated as zero. Hazard rules and prototype thresholds are in `src/earthscope/config.py`.
- `src/earthscope/incidents.py`: in-memory incident registry, duplicate handling, notes, and `Pending -> In Progress -> Resolved` state transitions. This is a demonstration workflow only.
- `index.html`: primary dashboard interface. MapLibre/deck.gl draws requested coordinates; Chart.js graphs share the UTC daily date axis returned by the backend. Missing dates align as `null`, not as zero.
- `src/earthscope/history_store.py` and `data/migrations/`: SQLite persistence, date/location/variable/resolution queries, country metadata, per-variable complete-calendar-year coverage, model/evaluation/prediction records, the v1-to-v2 normalized-provenance migration, and the v2-to-v3 country-metadata migration.
- `src/earthscope/history_ingest.py` and `scripts/ingest_nasa_power_history.py`: bounded five-year NASA POWER requests, transient retry/backoff, fill-value handling, unit conversion, gzipped raw-response retention with SHA-256, idempotent upserts, and seven-day overlap refreshes.
- `src/earthscope/prediction_model.py` and `scripts/train_temperature_model.py`: NumPy standardized ridge training, chronological validation/test metrics against persistence and seasonal-naive baselines, saved JSON artifacts, one-day-ahead prediction, and durable evaluation/prediction records.
- `src/earthscope/climate_analysis.py`: shared-range multi-location comparison and descriptive annual trends from stored rows, including annual and seasonal aggregates, extrema with dates, completeness warnings, rankings, and the minimum ten-complete-year trend rule.
- `src/earthscope/climate_model_suite.py` and `scripts/train_climate_models.py`: 48-series one-day modelling (12 locations × 4 variables) with chronological training/selection/calibration/test splits, identical held-out dates for all three methods, split-conformal intervals, and an empirical display gate.
- `src/earthscope/graph_summaries.py`: deterministic summaries calculated from exactly the aligned arrays sent to Chart.js, including valid/missing counts, location/range statistics, trends, seasonal monthly means when sufficiently long, outlier screens, and pairwise descriptive associations.
- `app.py`: optional legacy Streamlit incident-list/map view that reads the wrapped `/api/incidents` response.

`components/`, `mock_data.py`, `script.js`, the root `style.css`, and `assets/style.css` are retained legacy files. They are not imported by the current browser dashboard; `components/` functions remain covered by tests where applicable. They must not be mistaken for the active API or data sources.

## Observation contract

An observation contains:

```text
location_id, location_name: str
latitude: float (-90..90), longitude: float (-180..180)
temperature_c: float | None       (°C)
humidity_pct: float | None        (%)
wind_speed_kmh: float | None      (km/h; NASA POWER WS10M converted from m/s × 3.6)
rainfall_mm: float | None         (NASA POWER daily precipitation amount, mm/day)
observed_at: str                  (UTC daily date key, serialized at 00:00:00Z)
data_source: str
source_metadata: object | optional (constrained API/version, UTC, source labels, parameter names/units)
is_simulated: bool
note: str | optional
```

NASA POWER's daily values represent a daily product. `observed_at` is a date index and must not be presented as the instant of an in-situ observation. The requested coordinates do not make the data weather-station measurements. See [`dataset_sources.md`](dataset_sources.md) for source and unit details.

A missing value remains `None`. NASA POWER fill values such as `-999` and non-finite numbers are not valid measurements. Coordinates and non-missing measurements must pass the canonical ranges in `config.py`; invalid records are rejected rather than clamped.

## Dashboard response

`GET /api/dashboard` returns `mode`, `requested_mode`, `is_simulated`, `notes`, `range`, `retrieved_at`, `source_metadata`, `stations`, `series`, `incidents`, `rejected`, `threshold_set`, and `disclaimer`.

Each station entry supplies the map marker, latest day with at least one available measurement, explainable risk fields, measurements, data source, and source metadata. `series` is keyed by location ID. Every selected location has the same sorted daily `dates` array; an absent observation is represented by `null` in that field's values.

`GET /api/incidents` returns an object with an `incidents` list. Action routes return the updated incident object. Incident data stores for NASA POWER mode and demo mode are separate, but both live only in process memory and reset on restart.

## Historical archive, predictions, and summaries

Historical dashboard mode queries only `data/historical/earthscope_power.sqlite3`; it does not fall back to the demo dataset. `data/raw/nasa_power_history/` preserves the original compressed NASA responses. Schema version 2 stores response-level metadata and the raw SHA-256/path once in `source_responses`, and each daily-variable row references the shared response by `source_response_id`. Schema version 3 adds `country_name` and `country_code` to `locations`. Existing version 1 archives are rebuilt and compacted by migration 002 and version 2 archives are upgraded by migration 003 when `HistoryStore` first opens them. Natural-key uniqueness prevents duplicate location/dataset/variable/day/resolution rows. `--update` refreshes an overlapping seven-day tail.

The archive holds 446,364 daily-variable observations for 12 city coordinates in 12 countries: five locations from 1981-01-01 to 2026-09-14 with 45 complete shared years, and seven locations from 2015-01-01 to 2025-12-31 with 11 complete shared years. All 48 series have zero missing normalized values. A location is reported as qualified only when it has at least ten shared complete calendar years with every day valid for T2M, RH2M, WS10M, and PRECTOTCORR.

Historical API paths are `GET /api/history/availability`, `GET /api/history/observations`, `GET /api/dashboard?mode=historical`, and `GET /api/graph-summaries`. The observation route accepts one location, a supported variable, an inclusive UTC date range, and daily resolution. The UI derives selectable periods from the availability route and labels the archive source/date range. Each selection's summaries are recomputed from its plotted values; missing values remain null and do not become zero.

## Coverage, comparison, trends, and the model suite

`GET /api/climate/coverage` returns every stored location with per-variable record counts, missing counts, complete calendar years, and per-year completeness, plus a country grouping with `qualified_10_complete_years` and the shared `common_complete_years` list. The qualification rule is explicit in the response so the UI never has to infer it.

`GET /api/climate/comparison` (two or more locations) and `GET /api/climate/trends` (one or more) share `compare_locations` in `climate_analysis.py`. They query one variable over one inclusive shared UTC window, then compute per location: requested/recorded/valid/missing days and completeness; period mean (or precipitation total); minimum and maximum daily values with dates; annual aggregates with per-year completeness flags; complete-year count; an OLS trend over complete calendar years only, reported per year and per decade with an explicit "descriptive, not causal" interpretation; the largest consecutive-year change; seasonal daily means by hemisphere; and coverage warnings. Cross-location insights are limited to claims the stored values support (highest average, highest daily maximum with date, largest absolute trend). Windows longer than 50 years and fewer than two locations for comparison are rejected with 422.

`GET /api/climate/models/evaluation` serves the metadata stored in `models/climate_models.json`; `GET /api/predictions/next-day/all` generates one-day estimates for the requested locations from the end of each stored series. Both are labelled as archive-origin estimates, not forecasts. The model suite never trains during a request.

`GET /api/model/evaluation` and `GET /api/predictions/next-day` expose the original saved Cairo daily-temperature model. A separate command-line training workflow evaluates ridge against two same-row baselines on a later held-out period, then saves a JSON model and metadata. The API predicts one daily step after the latest archived temperature. It is a historical-pattern estimate, not a weather-service forecast, and is rendered separately from observations. Ingestion and training are finite CLI jobs; ordinary dashboard requests do not perform either long-running operation or retrain any model.

The live chart retains its existing 31-day request bound; historical dashboard ranges are limited to about ten years per request. See the project README for complete PowerShell installation, ingestion, training, testing, and startup commands and `dataset_sources.md` for measured coverage and source references.

## Running and testing

From the project root:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

The optional Streamlit view needs the API running separately: `python -m streamlit run app.py`. Automated tests use fixed fixtures; a successful live NASA POWER request is a smoke check, not a controlled integration test or independent validation of risk thresholds.
