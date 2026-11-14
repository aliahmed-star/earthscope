# EarthScope / GEOSTORM

EarthScope is a demonstration dashboard for exploring daily environmental data at selected coordinates, comparing countries over a shared archive period, and viewing transparent, rule-based prototype hazard assessments. The merged browser dashboard is served by FastAPI. The older Streamlit page remains available as a small optional incident-list view.

The project has been upgraded in place. The original five locations, map, readings table, four charts, summaries, risk levels, incident workflow, and Cairo temperature model are all still present. The upgrade adds seven more countries, archive-backed country comparison, annual climate trends, and a 48-series one-day estimate suite with held-out evaluation.

## Features

- NASA POWER Daily API requests for temperature, relative humidity, wind speed, and corrected precipitation.
- Explicit UTC daily requests, NASA response metadata retention, missing/fill-value handling, and unit conversion.
- A bundled SQLite archive of **446,364 daily-variable observations across 12 countries**.
- Archive coverage and completeness reporting: per-location, per-variable, and complete calendar years.
- Shared-date-range comparison for two or more countries with annual and seasonal summaries, extrema and dates, completeness warnings, rankings, observed change, variability, and descriptive trends.
- Annual climate-trend analysis computed from complete calendar years only.
- 48 evaluated one-day estimate models (12 locations × 4 variables) with chronological splits, identical held-out dates for baselines, and empirically gated prediction intervals.
- Offline demonstration observations that are labelled as simulated; live-request failures do not silently become real measurements.
- Explainable prototype hazard rules for heat, cold, wind, heavy rainfall, and wildfire-favourable conditions.
- A location map, daily measurement table, four time-series charts, incident list, and simulated response-state workflow.
- Location/date selection, bounded request caching, and clear source/fallback notes.

The dashboard uses NASA POWER gridded daily products at requested coordinates. These are not in-situ weather-station readings. Rainfall is shown as a daily amount (mm/day) and annual rainfall as a sum in mm/year. The hazard thresholds are prototype values, not official warnings or validated predictions. Incident actions only change an application status; they do not contact emergency services.

## Architecture

`index.html` contains the browser interface and uses MapLibre/deck.gl and Chart.js from pinned public CDN URLs. It calls the same-origin FastAPI endpoints in `api.py`. `dashboard_service.py` fetches selected locations in parallel, applies a 31-day maximum range and a 10-minute/128-entry in-memory cache, passes NASA POWER values through `src/earthscope/providers/nasa_power.py` and `src/earthscope/data_loader.py`, assesses them with `analysis.py`, and registers alerts in the in-memory `incidents.py` store. NASA failures or responses with no usable observations may result in labelled simulated demo data from `data/processed/demo_observations.json`.

The core logic under `src/earthscope/` is shared with the optional Streamlit incident view. `components/`, `mock_data.py`, the root `script.js`, and the standalone CSS files are retained legacy assets; they are not loaded by the current `index.html`/FastAPI dashboard. `docs/architecture.md` gives the current request flow, `docs/dataset_sources.md` is the maintained source registry, and `docs/model_evaluation.md` records the model method and all 48 held-out results.

## Data source

The integrated source is the NASA POWER Daily API point endpoint. The current request uses the `RE` community, JSON, and `time-standard=UTC`. NASA POWER response metadata is passed through for API name/version, time standard, source labels, and parameter descriptions/units when provided. A bounded live smoke request succeeded during the development audit; source details and candidate-source evaluation are documented in [`docs/dataset_sources.md`](docs/dataset_sources.md).

NASA POWER's referencing guide asks users of its data products to include the POWER project reference and the data reference, including service name, version, and access date. The dashboard surfaces the returned service/version and retrieval timestamp; use the [official referencing guide](https://power.larc.nasa.gov/docs/referencing/) for formal publications or redistribution.

No API key or credential is configured or required by the current client request. NOAA CDO, NASA Earthdata, AppEEARS, Giovanni, SWOT, and GPM IMERG are not implemented. NOAA CDO is recorded as an evaluated candidate requiring an access token and a defined station-comparison method. No NASA endorsement is claimed.

## Historical archive and coverage

The bundled archive was retrieved from NASA POWER's [Daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) with `community=RE`, JSON output, and `time-standard=UTC`. It is stored in `data/historical/earthscope_power.sqlite3`.

| Group | Locations | Stored dates | Days per series | Complete shared years |
|---|---|---|---|---|
| Original five | Cairo, Phoenix, Tokyo, Sydney, Manila | 1981-01-01 – 2026-09-14 | 16,693 | 45 (1981–2025) |
| Added seven | Delhi, Jakarta, London, Nairobi, Reykjavík, São Paulo, Toronto | 2015-01-01 – 2025-12-31 | 4,018 | 11 (2015–2025) |

- **12 countries, 12 locations, 48 series, 446,364 stored daily-variable observations.**
- Every series has **zero missing normalized values**. Nothing was interpolated, filled, or invented.
- A country qualifies only when its location has **at least 10 shared complete calendar years** in which every day of the year has a valid value for all four variables. All 12 qualify: the original five with 45 complete years, the added seven with 11.
- The four parameters are T2M (°C), RH2M (%), WS10M (raw m/s converted to km/h using ×3.6), and PRECTOTCORR (mm/day). They are NASA POWER grid-cell daily estimates, not weather-station observations. Parameter names and units follow NASA's [parameter documentation](https://power.larc.nasa.gov/docs/tutorials/parameters/); the [meteorology methodology](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/) describes the product lineage and its near-real-time transition.
- 71 gzipped original NASA responses are retained in `data/raw/nasa_power_history/` (1,995,885 bytes) with request metadata and SHA-256 digests of the decompressed payloads; all 71 verify. The SQLite file is 123,293,696 bytes. Exact request metadata and hashes are stored in `source_responses`.

The archive schema is version 3. Migration `002_normalize_history_provenance.sql` converted the original v1 layout to normalized response-level provenance; migration `003_location_country_metadata.sql` adds country name and ISO country code to each location. Older archives are migrated automatically when `HistoryStore` opens them. Re-running ingestion is duplicate-safe; `--update` refreshes a seven-day overlap so lagging or corrected values can replace older rows. Requests are split at five years. The full historical archive is not downloaded again when the page loads; live mode keeps its existing bounded point requests.

## Country comparison and annual trends

`GET /api/climate/comparison` compares two or more locations over one shared UTC date range and one variable. It returns, per location: requested/recorded/valid/missing days and completeness, the period mean or precipitation total, minimum and maximum daily values with dates, annual aggregates for every calendar year with per-year completeness, the number of complete years, a descriptive OLS trend with per-year and per-decade slope, the largest consecutive-year change, seasonal daily means, and coverage warnings. It also returns cross-location insights (highest average, highest daily maximum with its date, largest absolute trend) and explicit caveats.

`GET /api/climate/trends` uses the same calculation with a single location allowed. Annual aggregates use only **complete calendar years**, so a partial current year is excluded from the annual chart and the trend fit. Temperature, humidity, and wind are aggregated as annual arithmetic means of daily values; precipitation is aggregated as an annual sum of valid daily values in mm/year. Seasonal summaries use meteorological seasons assigned by hemisphere from calendar months, not a locally calibrated wet/dry classification.

Trends are ordinary least-squares descriptions of annual aggregates. They are not causal claims, not statistical-significance tests, and not attributions. A selection with fewer than ten complete annual means returns status `insufficient_complete_years` with no slope, and the interface says the trend rate is not computed.

## One-day archive-origin estimates

`scripts/train_climate_models.py` trains and evaluates **48 models** — one per location and variable — and writes `models/climate_models.json`. The method and full result table are in [`docs/model_evaluation.md`](docs/model_evaluation.md).

- Features: day-of-year sine/cosine, lags of 1, 2, 7, 14, 30, and 365 days, and trailing 7/30-day means from the same series.
- Chronological splits: training through 2019, method selection on 2020, interval calibration on 2021–2022, held-out test on 2023–2025 (1,096 target days per series).
- Ridge, persistence, and previous-year seasonal naive are scored on **identical held-out dates**. Ridge is selected for 45 series, persistence for 3 (Cairo, Delhi, and Phoenix precipitation).
- A nominal 90% split-conformal interval is displayed only when the held-out sample is at least 100 and empirical held-out coverage is 85–95%. **47 of 48 series pass.** Nairobi precipitation reaches only 83.5%, so its estimate is shown with "uncertainty not reliably quantified" and no interval.
- Cairo T2M, the original model, scores MAE 0.953 °C, RMSE 1.312 °C, R² 0.964 on the held-out years, against persistence 1.043 °C and seasonal naive 2.297 °C.

`GET /api/climate/models/evaluation` returns the stored evaluation metadata; `GET /api/predictions/next-day/all` returns one-day estimates for the requested locations. The older single-series Cairo endpoints remain: `GET /api/model/evaluation` and `GET /api/predictions/next-day`.

These are archive-origin statistical estimates. They are **not operational weather forecasts** and they do not predict disasters, impacts, or official warnings. A target date beyond the stored archive has no stored observed value, so it cannot be verified.

## API summary

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Service health |
| `GET /api/stations` | Configured live locations |
| `GET /api/dashboard` | Live, historical, or simulated dashboard payload |
| `GET /api/history/availability` | Stored archive coverage only |
| `GET /api/history/observations` | One location/variable over an inclusive UTC date range |
| `GET /api/climate/coverage` | Country qualification and per-variable complete years |
| `GET /api/climate/comparison` | Shared-range multi-country comparison |
| `GET /api/climate/trends` | Annual aggregates and descriptive trend |
| `GET /api/climate/models/evaluation` | Stored 48-series evaluation metadata |
| `GET /api/predictions/next-day/all` | One-day estimates for selected locations |
| `GET /api/graph-summaries` | Summaries of exactly the plotted arrays |
| `GET /api/model/evaluation`, `GET /api/predictions/next-day` | Original Cairo T2M model |
| `GET /api/incidents`, `POST /api/incidents/{id}/{action}` | In-memory demonstration incidents |

## Requirements

- Python 3.11 or newer.
- Dependencies in `requirements.txt`.
- An internet connection for NASA POWER requests and for the browser map/chart libraries. Simulated demo mode and the bundled archive can be served locally without NASA access.

No `.env` file is required for the standard deployment. Optional environment variables:

- `EARTHSCOPE_CORS_ORIGINS`: comma-separated exact origins for a separately hosted frontend. The default same-origin dashboard does not need CORS.
- `EARTHSCOPE_API_URL`: FastAPI base URL for the optional Streamlit page; defaults to `http://127.0.0.1:8000`.
- `EARTHSCOPE_HISTORY_DB`: path to an alternative SQLite archive.

Do not place secrets in source files or commit environment files.

## Install, test, and run

Linux/macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Windows PowerShell (run from the extracted project directory):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:EARTHSCOPE_HISTORY_DB = Join-Path $PWD "data\historical\earthscope_power.sqlite3"
python -m pytest -q
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. If port 8000 is already in use (Windows error 10048), use another port:

```powershell
python -m uvicorn api:app --host 127.0.0.1 --port 8001
```

then open <http://127.0.0.1:8001/>.

The supplied ZIP already includes the verified archive, raw NASA responses, and trained models, so a full download or retraining is not required. To rebuild the archive in a new, empty database, stop the server if running and run the ingestion command (71 live requests of at most five years each):

```powershell
python scripts\ingest_nasa_power_history.py --start-date 1981-01-01 --end-date 2026-09-14
```

For incremental refreshes, run `python scripts\ingest_nasa_power_history.py --update`; it defaults to the conservative latest-data cutoff and refreshes overlapping dates. To retrain the 48-series model suite (a few minutes of CPU, no network):

```powershell
python scripts\train_climate_models.py
```

To run the optional Streamlit incident list, keep FastAPI running in one terminal and run this in another:

```bash
python -m streamlit run app.py
```

For a non-default API address, set `EARTHSCOPE_API_URL` before starting Streamlit.

## Tests and verification notes

The automated suite has **138 passing tests**. It covers observation validation, hazard thresholds and explanations, NASA POWER parsing/fill values, incident transitions, the dashboard API, map/chart construction, date alignment, selection filtering, metadata, fallback labelling, cache reuse, complete-year qualification, shared-range comparison, seasonal summaries, annual trends, the new climate endpoints, real-archive estimates, and interval gating. Run `python -m pytest -q` from the project root.

Automated tests use deterministic fixtures for repeatability, with a small number of real-archive integration checks. Separately, the NASA POWER backfill and its SQLite/query/model/API paths were exercised on 2026-11-14. That verifies data retrieval and software processing, not independent meteorological accuracy against weather stations.

## Known limitations

- Hazard thresholds are educational prototype rules and are not validated meteorological warning criteria. They are not a disaster predictor and must not be presented as official warnings.
- Each "country" is represented by one city coordinate, not a national average. NASA POWER supplies daily gridded products; values are grid-cell estimates, not station measurements.
- Seven of the twelve locations have 11 complete years (2015–2025). A shared window that starts before 2015 therefore reports lower completeness for those countries and fewer complete years; the missing days stay missing and are never filled.
- No independent NOAA station validation, flood observation, authoritative operational weather forecast, anomaly baseline, or impact model is integrated.
- One-day estimates are historical-pattern estimates for a single variable. They are not weather forecasts and have no skill assessment against operational numerical weather prediction.
- Prediction intervals are shown only where held-out calibration passed; Nairobi precipitation has none. Coverage inside the 85–95% band is approximate, not exact.
- Annual trends are descriptive least-squares fits. They carry no significance test, no attribution, and no causal interpretation.
- NASA POWER may return missing values, delayed values, or incomplete coverage. The dashboard preserves missingness and labels demo fallback.
- Incident state is in memory and resets when the FastAPI process restarts. It is not a dispatch or emergency-management system.
- The browser interface depends on the configured public CDN hosts for MapLibre, deck.gl, and Chart.js.
- Deployment has not been performed or assessed. This prototype is intended for local demonstration, not production incident response.

## Website link
Hosted EarthScope site: https://earthscope26-j6mjzk58.manus.space

Access note: The current deployment is access-controlled. An unauthenticated request returned HTTP 403 during a check on 14 November 2026, so confirm sharing permissions before sending this link to people outside the project account.