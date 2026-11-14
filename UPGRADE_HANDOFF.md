# EarthScope upgrade — handoff

**Date:** 14 November 2026  
**Working copy:** `/home/ubuntu/EARTHSCOPE_enhanced_2026-11-14` (the same copy that was already being upgraded; no new project was created)  
**Original copy:** `/home/ubuntu/EARTHSCOPE_working/merged` — untouched

This document is the single entry point for the upgrade: what changed, what is verified, how to run and test it, and what to click during a demonstration.

## 1. What was upgraded

The existing FastAPI + single-page dashboard was extended in place. Nothing was rebuilt from a template, and every original feature still works:

- live NASA POWER mode, the location map, the readings table, the four time-series charts;
- plotted-data summaries, prototype risk levels, and the simulated incident workflow;
- the original Cairo one-day temperature model and its endpoints.

New in this upgrade:

1. **Seven additional countries** in the SQLite archive, for 12 in total, all meeting a strict complete-year rule.
2. **Archive coverage panel** with per-variable complete calendar years and missing counts.
3. **Country comparison panel** over one shared UTC range: annual and seasonal summaries, extrema with dates, completeness warnings, rankings, observed change, variability, and descriptive trends.
4. **Annual climate-trend panel** built from complete calendar years only.
5. **48-series one-day estimate suite** (12 locations × 4 variables) with chronological evaluation, identical held-out dates for baselines, and empirically gated prediction intervals.

## 2. Qualified coverage

| Country | Location | Stored dates | Days per variable | Complete shared years |
|---|---|---|---:|---:|
| Egypt | Cairo | 1981-01-01 – 2026-09-14 | 16,693 | 45 (1981–2025) |
| United States | Phoenix | 1981-01-01 – 2026-09-14 | 16,693 | 45 (1981–2025) |
| Japan | Tokyo | 1981-01-01 – 2026-09-14 | 16,693 | 45 (1981–2025) |
| Australia | Sydney | 1981-01-01 – 2026-09-14 | 16,693 | 45 (1981–2025) |
| Philippines | Manila | 1981-01-01 – 2026-09-14 | 16,693 | 45 (1981–2025) |
| India | Delhi | 2015-01-01 – 2025-12-31 | 4,018 | 11 (2015–2025) |
| Indonesia | Jakarta | 2015-01-01 – 2025-12-31 | 4,018 | 11 (2015–2025) |
| United Kingdom | London | 2015-01-01 – 2025-12-31 | 4,018 | 11 (2015–2025) |
| Kenya | Nairobi | 2015-01-01 – 2025-12-31 | 4,018 | 11 (2015–2025) |
| Iceland | Reykjavík | 2015-01-01 – 2025-12-31 | 4,018 | 11 (2015–2025) |
| Brazil | São Paulo | 2015-01-01 – 2025-12-31 | 4,018 | 11 (2015–2025) |
| Canada | Toronto | 2015-01-01 – 2025-12-31 | 4,018 | 11 (2015–2025) |

- **446,364 daily-variable observations**, 48 series, **zero missing normalized values**.
- Qualification rule: at least **10 shared complete calendar years** with every day valid for T2M, RH2M, WS10M, and PRECTOTCORR. All 12 qualify.
- Nothing was interpolated, filled, or invented. Missing values stay missing and are counted in the UI.

## 3. NASA data and quality evidence

- Source: NASA POWER Daily Point API, community `RE`, JSON, `time-standard=UTC`, API version `v2.10.3`.
- Variables: `T2M` (°C), `RH2M` (%), `WS10M` (m/s converted ×3.6 to km/h), `PRECTOTCORR` (mm/day; annual sums in mm/year).
- **71** gzipped NASA responses retained, **1,995,885 bytes**, with request metadata and SHA-256 digests over the decompressed payload; **71 of 71 verify**.
- SQLite archive: `data/historical/earthscope_power.sqlite3`, schema **v3**, **123,293,696 bytes** after the final WAL checkpoint (no `-wal` or `-shm` sidecars remain), `PRAGMA integrity_check` = `ok`, `PRAGMA foreign_key_check` = 0 violations.
- Migrations: `002_normalize_history_provenance.sql` (v1→v2), `003_location_country_metadata.sql` (v2→v3, adds `country_name` and `country_code`).
- Values are NASA POWER **grid-cell estimates**, not weather-station readings. Each country is represented by one city coordinate.

## 4. Comparison and annual trends

`GET /api/climate/comparison` (2–15 locations) and `GET /api/climate/trends` (1–15) share `compare_locations` in `src/earthscope/climate_analysis.py`.

Per location the response includes: requested/recorded/valid/missing days and completeness, period mean (or precipitation total), minimum and maximum daily values with dates, annual aggregates with per-year completeness, complete-year count, OLS trend per year and per decade, largest consecutive-year change, seasonal daily means, and coverage warnings. Cross-location insights are limited to highest average, highest daily maximum with date, and largest absolute trend.

Annual aggregates use **complete calendar years only**. A trend needs **at least 10 complete annual values**, otherwise the status is `insufficient_complete_years` and no slope is returned. Temperature, humidity, and wind are annual means; precipitation is an annual sum. Seasons are meteorological seasons assigned by hemisphere. Trends are descriptive least squares: no significance test, no attribution, no causal claim.

Cairo T2M remains **+0.093 °C/year for 2016–2025** (10 annual means) and **+0.032 °C/year for 1981–2025** (45 annual means).

## 5. One-day estimate suite

`python scripts/train_climate_models.py` trains and evaluates 48 series and writes `models/climate_models.json`. Method and the full table are in [`docs/model_evaluation.md`](docs/model_evaluation.md).

| Split | Target dates | Samples per series | Purpose |
|---|---|---|---|
| Training | 1982-01-01 – 2019-12-31 | 13,879 (original five) / 1,461 (added seven) | Fit coefficients and standardization |
| Selection | 2020-01-01 – 2020-12-31 | 366 | Choose ridge, persistence, or seasonal naive |
| Calibration | 2021-01-01 – 2022-12-31 | 730 | Fit the split-conformal interval radius |
| Held-out test | 2023-01-01 – 2025-12-31 | 1,096 | Final metrics only |

- Features: day-of-year sine/cosine, lags 1/2/7/14/30/365 days, trailing 7- and 30-day means. All precede the target day.
- All three methods are scored on **identical** held-out dates. Ridge is selected for **45** series, persistence for **3** (Cairo, Delhi, Phoenix precipitation).
- A nominal 90% interval is displayed only with at least 100 held-out cases and empirical coverage between 85% and 95%. **47 of 48 pass** (85.4%–94.2% coverage). **Nairobi precipitation** covers **83.5%** and is shown without an interval, labelled "uncertainty not reliably quantified".
- Cairo T2M: MAE **0.953 °C**, RMSE **1.312 °C**, R² **0.964**; persistence 1.043 °C; seasonal naive 2.297 °C on the same dates.
- Temperature R² spans 0.744 (Jakarta) to 0.971 (Delhi). Precipitation R² is near zero or negative for most locations; that is reported, not hidden.

These are archive-origin estimates of one meteorological variable one day beyond the stored series. They are **not** operational weather forecasts and **do not** predict disasters.

## 6. Test and verification report

| Check | Result |
|---|---|
| `python -m pytest -q` | **138 passed** (9.65 s) |
| Python compilation (`compileall`) | passed, exit 0 |
| Inline JavaScript `node --check` | passed |
| HTML IDs referenced by `$()` | 45 references, 0 missing |
| Browser smoke test (`scripts/smoke_dashboard.py`) | passed: 12/12 coverage rows, comparison table ≥2 rows, 8 estimate rows, no console errors |
| SQLite `integrity_check` / `foreign_key_check` | `ok` / 0 violations |
| NASA response hashes | 71/71 payload digests match |
| Deck export and page render | 7 pages, visually checked |
| Video decode and audio level | H.264 1080p30, AAC 48 kHz, mean −18.4 dBFS |

## 7. Install, train, run

Windows PowerShell, from the extracted project directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:EARTHSCOPE_HISTORY_DB = Join-Path $PWD "data\historical\earthscope_power.sqlite3"
python -m pytest -q
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

If port 8000 is already used (Windows error 10048), start on another port and open the matching URL:

```powershell
python -m uvicorn api:app --host 127.0.0.1 --port 8001
```

Linux/macOS:

```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Optional rebuilds (not needed for the bundled archive):

```powershell
python scripts\ingest_nasa_power_history.py --start-date 1981-01-01 --end-date 2026-09-14
python scripts\train_climate_models.py
python scripts\smoke_dashboard.py --base-url http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000/> (or the alternate port).

## 8. Demonstration guide

1. **Coverage first.** Scroll to *Country-location archive coverage*. It should read `12/12 countries qualify · 446,364 stored rows`, with 12 rows, each showing `QUALIFIED`, its stored span, its complete shared years (45 or 11), and `0 missing` for all four variables.
2. **Compare two countries.** In *Country comparison*, keep Egypt and the United States selected (or tick others), set From `2015-01-01`, Through `2025-12-31`, Variable `Temperature · °C`, then click **Compare selected**. You get the annual chart with OLS lines, an insights block, a nine-column table (ranks, completeness, complete-year range, seasonal means, extrema with dates, OLS rate per decade, largest adjacent-year change), and the *Annual climate trends* table underneath.
3. **Change the variable.** Switch to `Precipitation · annual mm` and compare again: annual values become mm/year sums, and the caveat explains that missing days are not filled.
4. **Test a short window.** Set the range to a single year and compare: the trend is withheld with a message that ten complete years are required. This is the honest-failure path.
5. **Load estimates.** Click **Load estimates for selected countries**. Each row shows the variable, the estimate, the target date and archive input date, the selected method with held-out MAE/RMSE/n, and either a 90% interval with its test coverage or "Uncertainty not reliably quantified".
6. **See the withheld interval.** Select Kenya as well and reload estimates: Nairobi precipitation has no interval.
7. **Original dashboard.** Switch the mode selector to *Historical archive*, pick locations and dates, and run it: map, readings, four charts, summaries, risk levels, and the Cairo model panel all behave as before. *NASA POWER data* mode makes bounded live requests; *Simulated demo* is labelled simulated.
8. **Read the limits.** The panels and the footer state that values are gridded estimates, thresholds are prototype rules, and nothing is an official warning or a disaster prediction.

## 9. Changed and added files

**Application and data pipeline**

- `api.py` — coverage, comparison, trends, model-evaluation, and multi-location estimate endpoints.
- `dashboard_service.py` — historical range handling for the new panels.
- `index.html` — coverage, comparison, trends, and estimate panels plus their JavaScript wiring.
- `src/earthscope/history_store.py` — schema v3 handling, country metadata, complete-year coverage.
- `src/earthscope/climate_analysis.py` — new: shared-range comparison and annual trends.
- `src/earthscope/climate_model_suite.py` — new: 48-series training, evaluation, interval gating, estimates.
- `scripts/train_climate_models.py` — new: repeatable training CLI.
- `scripts/smoke_dashboard.py` — new: Playwright smoke test and screenshot capture.
- `data/migrations/003_location_country_metadata.sql` — new: country name and ISO code.
- `data/historical/earthscope_power.sqlite3` — expanded to 12 countries, 446,364 rows, schema v3.
- `data/raw/nasa_power_history/` — 71 retained responses (50 original + 21 new).
- `models/climate_models.json` — new: trained bundle, 48 evaluated series.

**Tests**

- `tests/test_climate_analysis.py` — new: qualification, comparison, seasons, trends.
- `tests/test_climate_model_suite.py` — new: real-archive estimate and interval gating.
- `tests/test_api.py`, `tests/test_history_store.py` — updated for the new endpoints and schema v3.

**Documentation**

- `README.md` — rewritten for the 12-country scope.
- `docs/model_evaluation.md` — new: method and all 48 held-out results.
- `docs/dataset_sources.md`, `docs/architecture.md` — updated archive, schema, and endpoint documentation.
- `EARTHSCOPE_FINAL_DEVELOPMENT_REPORT.md` — rewritten as the current upgrade record.
- `HISTORICAL_DATA_MODEL_IMPLEMENTATION_REPORT.md` — supersession note added; kept as the earlier milestone record.
- `PROJECT_UPGRADE_PLAN.md` — the plan followed for this upgrade.

**Submission bundle** (`submission_deliverables_2026-11-14/`)

- `EarthScope_Final_Presentation.pptx` — refreshed seven-slide deck with authentic panel captures.
- `EarthScope_Final_Project_Report.docx` — refreshed 10-page report.
- `EarthScope_30s_Demo.mp4` — refreshed 23.5 s video, 1080p30, synthetic narration disclosed.
- `EARTHSCOPE_NASA_DATA_AUDIT.md`, `EARTHSCOPE_SUBMISSION_STATUS.md` — updated audits and status.
- `assets/storyboard.md`, `assets/earthscope_video_narration.txt` — refreshed script and narration.
- `assets/earthscope_dataflow.mmd` / `.png`, `assets/earthscope_dataflow_light.mmd` / `.png` — updated diagrams.
- `assets/screenshots/archive_coverage_panel.png`, `country_comparison_panel.png`, `climate_trends_panel.png`, `model_suite_panel.png`, `dashboard_full_page.png` — new authentic captures.
- `assets/frames/` — refreshed video frames and contact sheet.

## 10. Limitations

- One city coordinate per country; these are not national averages.
- NASA POWER values are gridded estimates, not station observations; no independent station validation was performed.
- Seven countries have 11 complete years, so their trends and comparisons are shorter than the original five.
- One-day estimates use archived history only; there is no numerical weather prediction input and no skill assessment against an operational model.
- Intervals are shown only where calibration passed; coverage inside the 85–95% band is approximate.
- Annual trends are descriptive least squares with no significance test, attribution, or causal claim.
- Prototype thresholds are not official warnings; the incident store is in memory and resets on restart.
- No public deployment was performed, and nothing is claimed about NASA endorsement.
