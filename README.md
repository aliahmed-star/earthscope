# EarthScope / GEOSTORM

EarthScope is a demonstration dashboard for exploring daily environmental data at selected coordinates and viewing transparent, rule-based prototype hazard assessments. The merged browser dashboard is served by FastAPI. The older Streamlit page remains available as a small optional incident-list view.

## Features

- NASA POWER Daily API requests for temperature, relative humidity, wind speed, and corrected precipitation.
- Explicit UTC daily requests, NASA response metadata retention, missing/fill-value handling, and unit conversion.
- Offline demonstration observations that are labelled as simulated; live-request failures do not silently become real measurements.
- Explainable prototype hazard rules for heat, cold, wind, heavy rainfall, and wildfire-favourable conditions.
- A location map, daily measurement table, four time-series charts, incident list, and simulated response-state workflow.
- Location/date selection, bounded request caching, and clear source/fallback notes.

The dashboard uses NASA POWER gridded daily products at requested coordinates. These are not in-situ weather-station readings. Rainfall is shown as a daily amount (mm/day), not as an independently verified rolling 24-hour gauge total. The hazard thresholds are prototype values, not official warnings or validated predictions. Incident actions only change an application status; they do not contact emergency services.

## Architecture

`index.html` contains the browser interface and uses MapLibre/deck.gl and Chart.js from pinned public CDN URLs. It calls the same-origin FastAPI endpoints in `api.py`. `dashboard_service.py` fetches selected locations in parallel, applies a 31-day maximum range and a 10-minute/128-entry in-memory cache, passes NASA POWER values through `src/earthscope/providers/nasa_power.py` and `src/earthscope/data_loader.py`, assesses them with `analysis.py`, and registers alerts in the in-memory `incidents.py` store. NASA failures or responses with no usable observations may result in labelled simulated demo data from `data/processed/demo_observations.json`.

The core logic under `src/earthscope/` is shared with the optional Streamlit incident view. `components/`, `mock_data.py`, the root `script.js`, and the standalone CSS files are retained legacy assets; they are not loaded by the current `index.html`/FastAPI dashboard. `docs/architecture.md` gives the current request flow, and `docs/dataset_sources.md` is the maintained source registry.

## Data source

The integrated source is the NASA POWER Daily API point endpoint. The current request uses the `RE` community, JSON, and `time-standard=UTC`. NASA POWER response metadata is passed through for API name/version, time standard, source labels, and parameter descriptions/units when provided. A bounded live smoke request succeeded during the development audit; source details and candidate-source evaluation are documented in [`docs/dataset_sources.md`](docs/dataset_sources.md).

NASA POWER's referencing guide asks users of its data products to include the POWER project reference and the data reference, including service name, version, and access date. The dashboard surfaces the returned service/version and retrieval timestamp; use the [official referencing guide](https://power.larc.nasa.gov/docs/referencing/) for formal publications or redistribution.

No API key or credential is configured or required by the current client request. NOAA CDO, NASA Earthdata, AppEEARS, Giovanni, SWOT, and GPM IMERG are not implemented. NOAA CDO is recorded as an evaluated candidate requiring an access token and a defined station-comparison method.

## Historical archive, model, and plotted-data summaries

The bundled historical archive was retrieved from NASA POWER's [Daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) with `community=RE`, JSON output, and `time-standard=UTC`. On 2026-11-14, 50 live five-year-or-shorter requests stored 333,860 daily-variable rows for Cairo, Phoenix, Tokyo, Sydney, and Manila. Every one of the 20 location/variable series covers 1981-01-01 through 2026-09-14, with 16,693 rows and zero missing values. The parameters are T2M (°C), RH2M (%), WS10M (raw m/s converted to km/h using ×3.6), and PRECTOTCORR (mm/day). They are NASA POWER grid-cell daily estimates, not weather-station observations. Parameter names and returned units follow NASA's [parameter documentation](https://power.larc.nasa.gov/docs/tutorials/parameters/); the [meteorology methodology](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/) describes the product lineage and its near-real-time transition. The exact request metadata and SHA-256 hashes are retained.

The normalized SQLite archive is `data/historical/earthscope_power.sqlite3` (90,030,080 bytes at delivery). The 50 gzipped original NASA JSON responses in `data/raw/nasa_power_history/` total 1,485,323 bytes. Before expanding beyond Cairo T2M and precipitation, the ingestion and storage pipeline was validated against a real Cairo 2010–2019 response set. Re-running ingestion is duplicate-safe; `--update` refreshes a seven-day overlap so lagging or corrected values can replace older rows. Requests are split at five years. The `observations` table stores normalized values and references shared response-level provenance; migration 002 performs the v1-to-v2 conversion and compaction automatically when `HistoryStore` opens an older archive. The full historical archive is not downloaded again when the page loads; live mode keeps its existing bounded point requests.

The archived model is a lightweight standardized ridge regression for one-day-ahead Cairo T2M. Inputs are target day-of-year sine/cosine, daily lags (1, 2, 7, 14, 30, and 365 days), and prior 7/30-day rolling means. Alpha was selected on the 2020–2022 validation period (MAE 0.997 °C). The chronological target-date splits were 1982–2019 training (13,879 rows), 2020–2022 validation (1,096 rows), and the held-out 2023–2025 test (1,096 rows). The first train target is 1982 because the features and seasonal baseline require the prior year's observations. On the same test dates, ridge achieved MAE 0.953 °C, RMSE 1.312 °C, and R² 0.964. Persistence achieved 1.043 °C, 1.456 °C, and 0.955; previous-year seasonal naive achieved 2.297 °C, 2.965 °C, and 0.815. These are historical evaluation metrics, not a guarantee of future accuracy.

For a real API prediction from the archived series ending 2026-09-14, the model returned 28.82 °C for 2026-09-15. The same-date persistence and prior-year seasonal-naive estimates were 29.14 °C and 27.50 °C. This is an archive-origin statistical estimate, not an operational or current weather forecast; its target is outside the stored observation range and is not verified against a stored actual value. The JSON model and evaluation metadata are saved at `models/cairo_t2m_next_day.json` and `models/cairo_t2m_next_day.metadata.json`.

`GET /api/history/availability` reports only stored coverage. `GET /api/history/observations` filters by location, variable, inclusive dates, and daily resolution; `GET /api/dashboard?mode=historical` supplies historical chart series; `GET /api/graph-summaries` and the dashboard response summarize the same plotted arrays; `GET /api/model/evaluation` and `GET /api/predictions/next-day` expose the saved evaluation and prediction. For Cairo charts from 2016-01-01 through 2025-12-31, the deterministic summary found 3,653/3,653 plotted temperature values, a mean of 22.101 °C, an upward descriptive slope of 0.165 °C/year, a July mean of 30.645 °C, and a January mean of 12.153 °C. The summary labels this as descriptive rather than causal. A single-year selection correctly withholds a multi-year seasonal conclusion. Summary statistics are recalculated when the location or date selection changes; missing values remain missing and potential outliers are only statistical screens.

## Requirements

- Python 3.11 or newer.
- Dependencies in `requirements.txt`.
- An internet connection for NASA POWER requests and for the browser map/chart libraries. Simulated demo mode can be served locally without NASA access.

No `.env` file is required for the standard deployment. Optional environment variables:

- `EARTHSCOPE_CORS_ORIGINS`: comma-separated exact origins for a separately hosted frontend. The default same-origin dashboard does not need CORS.
- `EARTHSCOPE_API_URL`: FastAPI base URL for the optional Streamlit page; defaults to `http://127.0.0.1:8000`.

Do not place secrets in source files or commit environment files.

## Install and test

Linux/macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

Complete Windows PowerShell workflow for the bundled project (run from the extracted project directory):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:EARTHSCOPE_HISTORY_DB = Join-Path $PWD "data\historical\earthscope_power.sqlite3"
python scripts\train_temperature_model.py
python -m pytest -q
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

The supplied ZIP already includes the verified archive, raw NASA responses, and trained model, so a full download is not required. To build the archive in a new, empty database, stop the server if running and issue this separate command (50 live five-year-or-shorter requests):

```powershell
python scripts\ingest_nasa_power_history.py --start-date 1981-01-01 --end-date 2026-09-14
```

For incremental refreshes, run `python scripts\ingest_nasa_power_history.py --update`; it defaults to the conservative latest-data cutoff and refreshes overlapping dates. Opening an existing v1 database through the application automatically applies migration 002. After the server starts, open <http://127.0.0.1:8000/>. If port 8000 is already in use, use `--port 8001` and open <http://127.0.0.1:8001/> instead.

## Run the browser dashboard

From the repository root, with dependencies installed:

```bash
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. The dashboard requests NASA POWER data when NASA POWER mode is selected. If there is no usable live response, the API labels and displays the offline simulated fallback. Select **Simulated demo** to view the fixed demonstration scenario directly.

To run the optional Streamlit incident list, keep FastAPI running in one terminal and run this in another:

```bash
python -m streamlit run app.py
```

For a non-default API address, set `EARTHSCOPE_API_URL` before starting Streamlit.

## Tests and verification notes

The automated suite covers observation validation, hazard thresholds and explanations, NASA POWER parsing/fill values, incident transitions, the dashboard API, map/chart construction, date alignment, selection filtering, metadata, fallback labelling, and cache reuse. Run `python -m pytest -q` from the project root.

Automated tests use deterministic fixtures for repeatability. Separately, the real 50-request NASA POWER backfill and its SQLite/query/model/API paths were exercised on 2026-11-14. That verifies data retrieval and software processing, not independent meteorological accuracy against weather stations.

## Known limitations

- Hazard thresholds are educational prototype rules and are not validated meteorological warning criteria.
- NASA POWER supplies daily gridded products. Parameter lineage, spatial resolution, latency, and quality are product-specific; the application should not be interpreted as station-level real-time monitoring.
- No independent NOAA station validation, flood observation, authoritative operational weather forecast, anomaly baseline, or impact model is integrated. The statistical model is currently limited to Cairo daily temperature.
- NASA POWER may return missing values, delayed values, or incomplete coverage. The dashboard preserves missingness and labels demo fallback.
- Incident state is in memory and resets when the FastAPI process restarts. It is not a dispatch or emergency-management system.
- The browser interface depends on the configured public CDN hosts for MapLibre, deck.gl, and Chart.js.
- Deployment has not been performed or assessed. This prototype is intended for local demonstration, not production incident response.
