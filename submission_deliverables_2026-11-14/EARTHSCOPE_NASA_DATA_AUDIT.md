# EarthScope NASA Data and Model Audit

**Updated:** 14 November 2026  
**Project assessed:** EarthScope dashboard package with its NASA POWER SQLite archive, country comparison and annual-trend calculations, and 48-series one-day estimate suite.

## Findings at a glance

EarthScope keeps live NASA POWER Daily access and bundles a persisted multi-country NASA POWER archive. SQLite schema v3 contains **446,364 daily-variable observations** for **12 city coordinates in 12 countries**: Cairo, Phoenix, Tokyo, Sydney, Manila, Delhi, Jakarta, London, Nairobi, Reykjavík, São Paulo, and Toronto. The five original locations cover **1981-01-01 – 2026-09-14** with 45 complete shared years; the seven added locations cover **2015-01-01 – 2025-12-31** with 11 complete shared years. All 48 location-variable series contain zero missing normalized values. **71 original NASA response payloads** are retained as compressed source files with SHA-256 provenance.

A **48-series model suite** (12 locations × 4 variables) estimates the next daily value of each variable from that location's own archive. Evaluation is chronological: training through 2019, method selection on 2020, interval calibration on 2021–2022, and a held-out test on 2023–2025 with **1,096 target days per series**. Ridge is selected for 45 series and persistence for 3. **47 of 48 series pass the interval display rule**; Nairobi precipitation fails and is shown without an interval. These are statistical estimates of one meteorological variable, not disaster predictions or operational weather forecasts.

Comparison and trend calculations use actual stored observations over one shared UTC window. Trends fit ordinary least squares to **complete calendar years only** and are labelled descriptive, not causal. Cairo T2M remains **+0.093 °C/year for 2016–2025** and **+0.032 °C/year for 1981–2025**.

## Data and storage

The archive came from 71 live requests to the NASA POWER Daily Point API, split at five calendar years. It contains four variables per location: `T2M` in °C, `RH2M` in %, `WS10M` converted from m/s to km/h, and `PRECTOTCORR` in mm/day. Dates are daily UTC keys. The series are NASA POWER gridded estimates, not in-situ station observations. No values were interpolated, filled, or invented.

| Location | Country | Stored dates | Days per variable | Complete years |
|---|---|---|---:|---:|
| Cairo | Egypt | 1981-01-01 – 2026-09-14 | 16,693 | 45 |
| Phoenix | United States | 1981-01-01 – 2026-09-14 | 16,693 | 45 |
| Tokyo | Japan | 1981-01-01 – 2026-09-14 | 16,693 | 45 |
| Sydney | Australia | 1981-01-01 – 2026-09-14 | 16,693 | 45 |
| Manila | Philippines | 1981-01-01 – 2026-09-14 | 16,693 | 45 |
| Delhi | India | 2015-01-01 – 2025-12-31 | 4,018 | 11 |
| Jakarta | Indonesia | 2015-01-01 – 2025-12-31 | 4,018 | 11 |
| London | United Kingdom | 2015-01-01 – 2025-12-31 | 4,018 | 11 |
| Nairobi | Kenya | 2015-01-01 – 2025-12-31 | 4,018 | 11 |
| Reykjavík | Iceland | 2015-01-01 – 2025-12-31 | 4,018 | 11 |
| São Paulo | Brazil | 2015-01-01 – 2025-12-31 | 4,018 | 11 |
| Toronto | Canada | 2015-01-01 – 2025-12-31 | 4,018 | 11 |

The SQLite database is `data/historical/earthscope_power.sqlite3` (123,293,696 bytes). It stores observations, locations with country metadata, variables, datasets, ingestion runs, source-response provenance, model versions, evaluation records, and prediction records. Natural-key constraints prevent duplicate location/dataset/variable/date/resolution records. The 71 compressed original responses total 1,995,885 bytes; their stored SHA-256 digests were verified over the decompressed response payload. `PRAGMA integrity_check` returned `ok` and `PRAGMA foreign_key_check` returned zero violations.

## Data quality and completeness

The qualification rule is deliberately strict: a location counts as a country-level series only if it has **at least ten shared complete calendar years** in which every day of each year has a valid value for all four variables. All 12 locations pass: five with 45 complete years, seven with 11.

Quality evidence from the stored rows:

- Zero missing normalized values across all 48 series; no interpolation or forward fill.
- Each complete year is validated against its true length (365 days, or 366 in leap years) before it is used in an annual aggregate or trend.
- Partial calendar years at the edges of a selection are excluded from annual aggregates and trend fits, and the response says so.
- Coverage warnings are per location: missing days in the requested window are reported as a count and are never filled.
- Precipitation is kept as a daily amount (mm/day); annual rainfall is the sum of valid daily values (mm/year), with no correction for missing days.
- Fill values such as `-999` and non-finite numbers are rejected at ingestion, not converted to zero.

Migration `002_normalize_history_provenance.sql` converted the original layout to normalized response-level provenance; `003_location_country_metadata.sql` adds country name and ISO country code. Both apply automatically when an older archive is opened.

NASA references: [Daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/), [parameter dictionary](https://power.larc.nasa.gov/docs/tutorials/parameters/), and [meteorology data sources and methodology](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/).

## Comparison and annual trends

`GET /api/climate/comparison` compares two or more locations over one shared UTC date range and one variable. Per location it returns requested/recorded/valid/missing days and completeness, the period mean (or precipitation total), minimum and maximum daily values with their dates, annual aggregates with per-year completeness, complete-year count, an OLS trend per year and per decade, the largest consecutive-year change, seasonal daily means, and coverage warnings. Cross-location insights are restricted to what the stored values support: highest average, highest daily maximum with date, and largest absolute trend.

Seasonal summaries use meteorological seasons assigned by hemisphere from calendar months; they are not locally calibrated wet/dry season classifications. A trend is computed only when at least ten complete annual aggregates exist; otherwise the status is `insufficient_complete_years` and no slope is reported.

For Cairo T2M, the annual-mean fits remain **+0.093 °C/year over 2016–2025** (10 yearly values) and **+0.032 °C/year over 1981–2025** (45 yearly values). Trend windows stop at 2025 so every included year is complete; the archive itself continues to 2026-09-14. These slopes are descriptive and carry no significance test, attribution, or causal interpretation.

## One-day model suite and evaluation

Each series is modelled separately with standardized ridge regression on day-of-year sine/cosine, lags of 1, 2, 7, 14, 30, and 365 days, and trailing 7- and 30-day means. All features precede the target day.

| Split | Target dates | Samples per series | Use |
|---|---|---|---|
| Training | 1982-01-01 – 2019-12-31 | 13,879 (original five) / 1,461 (added seven) | Fit coefficients and standardization |
| Selection | 2020-01-01 – 2020-12-31 | 366 | Choose ridge, persistence, or seasonal naive by MAE |
| Calibration | 2021-01-01 – 2022-12-31 | 730 | Fit the split-conformal interval radius |
| Held-out test | 2023-01-01 – 2025-12-31 | 1,096 | Final metrics; never used for fitting or selection |

All three methods are scored on the same 1,096 held-out dates. Ridge is selected for **45** series and persistence for **3** (Cairo, Delhi, and Phoenix precipitation). Temperature R² ranges from 0.744 (Jakarta) to 0.971 (Delhi). Daily precipitation is the hardest target: R² is near zero or negative for most locations, and the best MAE is only slightly better than persistence. Negative R² values are reported rather than hidden.

The interval is a symmetric split-conformal band around the selected method's prediction, built from calibration residuals. It is displayed only when there are at least 100 held-out cases and empirical held-out coverage is between 85% and 95%. **47 of 48 series pass**, with coverage between 85.4% and 94.2%. **Nairobi precipitation covers only 83.5%** of held-out days, so its estimate is shown with the explicit statement that uncertainty is not reliably quantified and with no interval. No confidence percentage is invented for it.

The full per-series table (MAE, RMSE, R², all three baseline MAEs, interval status, coverage, and mean width) is in `docs/model_evaluation.md`.

## What the project does and does not establish

The dashboard provides live NASA POWER requests, archived historical queries, country comparison, descriptive annual trends, a 48-series evaluated one-day estimate suite, and a separately labelled simulated incident workflow. Threshold-based incident levels remain prototype rules. They are not official warnings and are not a model of disaster occurrence or impact.

The model suite estimates four meteorological variables one day beyond each stored series. It does not predict earthquakes, floods, fires, storms, droughts, landslides, or any other disaster, and it has no operational numerical-weather-prediction input, no station-based independent validation, and no calibrated disaster-event probabilities. NASA POWER values are gridded estimates; a city coordinate selects a grid cell and should not be read as a neighbourhood or station measurement. A one-day statistical estimate must not be presented as a current operational weather forecast.

No public deployment or emergency-service integration is claimed. Incident actions are local demonstration actions. The project depends on external browser libraries for maps and charts.

## Verification

The final automated suite passed **138 tests**, including complete-year qualification, shared-range comparison, seasonal summaries, annual trends, the new climate endpoints, real-archive one-day estimates, and interval gating. Additional checks passed for Python compilation, inline JavaScript syntax and HTML IDs, live-database API routes, raw-file hashes, and SQLite/foreign-key integrity. The historical dashboard was exercised from 2016-01-01 through 2025-12-31; its plotted summaries matched the summary API. The metrics above were read from `models/climate_models.json`, generated from the bundled archive on 2026-11-14.

## References

- [NASA POWER Daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/)
- [NASA POWER parameter dictionary](https://power.larc.nasa.gov/docs/tutorials/parameters/)
- [NASA POWER meteorology data sources and methodology](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/)
- [Model evaluation details](../../docs/model_evaluation.md)
- [Historical data and model implementation report](../../HISTORICAL_DATA_MODEL_IMPLEMENTATION_REPORT.md)
