# EarthScope climate-intelligence upgrade plan

## Current architecture inspected

The existing app is a same-origin FastAPI backend (`api.py` and `dashboard_service.py`) with a single-file HTML/JavaScript dashboard (`index.html`). NASA POWER daily values are normalized into an idempotent SQLite archive by `src/earthscope/history_ingest.py` and `history_store.py`. The app preserves the existing interactive map, readings, four charts, graph summaries, threshold-based prototype incident workflow, and one Cairo T2M standardized-ridge model with chronological evaluation.

## Implementation approach

1. Verify additional candidate city-coordinate records against actual NASA POWER daily responses for 2015–2025. Count a country only when each of the four primary variables has at least ten complete calendar years; do not interpolate missing records.
2. Add country identity to registered locations and a safe SQLite migration. Expand the location registry only with verified candidates; ingest and retain NASA source responses, hashes, UTC dates, raw values, normalized units, and missing values.
3. Extend the archive availability API/UI with per-variable coverage, missingness, complete calendar years, and a transparent qualified/unqualified indicator.
4. Add archive-backed comparison and trend endpoints, using shared selected locations and dates. Calculate daily extrema, annual temperature/humidity/wind means, annual precipitation totals, hemisphere-aware seasonal summaries, descriptive OLS trend rates, year-to-year changes, and rankings from database values only.
5. Extend one-day estimates to qualified location-variable series using chronological splits and identical test dates for ridge and persistence/seasonal-naive baselines. Calibrate an empirical interval on a separate earlier calibration window and disclose held-out interval coverage; suppress intervals when coverage is not sufficiently supported. Keep all model outputs distinct from operational forecasts and disaster warnings.
6. Add comparison, trend, archive-quality, and evaluation panels to the current dashboard without removing existing features. Add unit, coverage, missingness, chronology/leakage, API, and UI-data tests.
7. Update NASA source/quality documentation, model limitations, Windows setup/run commands, and the final change/test report. Do not publish the website or claim disaster prediction.

## Project structure

- `api.py`: FastAPI routes and request validation.
- `dashboard_service.py`: existing live/demo/historical dashboard data assembly.
- `src/earthscope/providers/nasa_power.py`: official NASA POWER point client and unit normalization.
- `src/earthscope/history_ingest.py`: bounded/retryable ingestion and raw-response provenance.
- `src/earthscope/history_store.py`, `data/migrations/`: normalized SQLite storage and migrations.
- `src/earthscope/`: new archive comparison/trend/model evaluation logic alongside existing model/summary modules.
- `scripts/`: repeatable archive and model commands.
- `index.html`: existing dashboard with additive comparison, trends, coverage, and forecast-evaluation UI.
- `tests/`, `docs/`, `submission_deliverables_2026-11-14/`: verification and updated handoff documentation.
