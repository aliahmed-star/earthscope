# EarthScope / GEOSTORM — Development Report

**Updated:** 14 November 2026  
**Project:** EarthScope dashboard upgraded in place with a 12-country NASA POWER archive, country comparison, annual trends, and a 48-series one-day estimate suite  
**Readiness:** Ready for local demonstration; not represented as an operational warning, forecast, or disaster-prediction system.

## What changed in this upgrade

The original FastAPI/browser dashboard was kept and extended. Live NASA POWER mode, the map, readings table, four charts, plotted-data summaries, prototype risk levels, incident workflow, and the Cairo temperature model all still work as before. The upgrade adds:

- seven additional NASA POWER locations, bringing the archive to 12 countries;
- archive coverage and completeness reporting, including complete-calendar-year qualification;
- shared-date-range country comparison with annual and seasonal summaries, extrema and dates, completeness warnings, rankings, observed change, variability, and descriptive trends;
- annual climate-trend analysis from complete calendar years only;
- 48 evaluated one-day estimate models (12 locations × 4 variables) with held-out metrics and empirically gated prediction intervals.

No new application template was created and the original working copy was left untouched. This is the same dashboard, upgraded.

## Data archive

`data/historical/earthscope_power.sqlite3` (schema v3) contains **446,364 daily-variable observations** for **12 city coordinates in 12 countries**:

| Group | Locations | Stored dates | Days per series | Complete shared years |
|---|---|---|---|---|
| Original five | Cairo, Phoenix, Tokyo, Sydney, Manila | 1981-01-01 – 2026-09-14 | 16,693 | 45 (1981–2025) |
| Added seven | Delhi, Jakarta, London, Nairobi, Reykjavík, São Paulo, Toronto | 2015-01-01 – 2025-12-31 | 4,018 | 11 (2015–2025) |

Every one of the 48 series has zero missing normalized values. A country qualifies only with at least ten shared complete calendar years in which all days are valid for T2M, RH2M, WS10M, and PRECTOTCORR; all 12 qualify. The four variables are T2M (°C), RH2M (%), WS10M (km/h after ×3.6 conversion from m/s), and PRECTOTCORR (mm/day). The underlying NASA POWER values are daily gridded estimates, not station readings.

Seventy-one compressed NASA source responses are included and verified by SHA-256 (1,995,885 bytes). Schema v2 stores daily records and normalized response provenance; migration `002_normalize_history_provenance.sql` upgrades a v1 archive. Migration `003_location_country_metadata.sql` adds country name and ISO country code. Natural-key uniqueness protects against duplicate ingestion, and incremental updates use a seven-day overlap with bounded requests and retries. The database file is 123,293,696 bytes.

## Comparison and trends

`GET /api/climate/comparison` compares two or more locations over one shared UTC range and one variable. It reports completeness, period means or totals, daily extrema with dates, annual aggregates with per-year completeness, complete-year counts, an OLS trend per year and per decade, the largest consecutive-year change, seasonal daily means, coverage warnings, and cross-location insights. `GET /api/climate/trends` uses the same calculation for one or more locations.

Annual aggregates use complete calendar years only; partial edge years are excluded and the exclusion is reported. Temperature, humidity, and wind are annual means; precipitation is an annual sum in mm/year. A trend requires at least ten complete annual values, otherwise the response says `insufficient_complete_years`. Trends are descriptive, with no significance test and no causal claim.

Cairo T2M annual-mean slopes remain **+0.093 °C/year for 2016–2025** (10 annual means) and **+0.032 °C/year for 1981–2025** (45 annual means). The archive itself continues to 2026-09-14; trend windows stop at 2025 so every included year is complete.

## One-day estimate suite

`scripts/train_climate_models.py` trains and evaluates 48 series and writes `models/climate_models.json`. Features are day-of-year sine/cosine, lags of 1, 2, 7, 14, 30, and 365 days, and trailing 7/30-day means. Splits are chronological: training through 2019, method selection on 2020, interval calibration on 2021–2022, and a held-out test on 2023–2025 with 1,096 target days per series. Ridge, persistence, and seasonal naive are scored on identical held-out dates; ridge is selected for 45 series and persistence for 3.

A nominal 90% split-conformal interval is displayed only when the held-out sample is at least 100 and empirical coverage is 85–95%. **47 of 48 series pass**; Nairobi precipitation reaches 83.5% and is shown without an interval, labelled "uncertainty not reliably quantified".

Cairo T2M, the original saved model, scores MAE 0.953 °C, RMSE 1.312 °C, and R² 0.964 on the held-out years; persistence scores 1.043 °C, 1.456 °C, and 0.955 on the same dates; previous-year seasonal naive scores 2.297 °C, 2.965 °C, and 0.815. The example archive-origin estimate is 28.82 °C for 2026-09-15, from input through 2026-09-14; that target date has no stored observed value.

## Validation and limitations

The final suite passed **138 tests**, including coverage qualification, comparison, seasonal summaries, trends, the new climate endpoints, real-archive estimates, and interval gating. Python compilation, inline JavaScript syntax and HTML IDs, a browser smoke test of the new panels, raw-response hashes, and SQLite integrity checks also passed.

The incident workflow remains a simulated prototype threshold feature; it is not a trained or validated disaster model. The one-day estimates cover four meteorological variables at 12 city coordinates and are not operational weather forecasts. There is no independent station evaluation and no numerical weather prediction input, and NASA POWER values represent grid cells. Seven countries have only 11 complete years. No production deployment is claimed.

For the full route list, model features and per-series metrics, schema/migration details, exact Windows PowerShell commands, and the complete file inventory, see `HISTORICAL_DATA_MODEL_IMPLEMENTATION_REPORT.md`, `docs/model_evaluation.md`, and `README.md`.
