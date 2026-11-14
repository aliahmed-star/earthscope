# EarthScope NASA Data and Model Audit

**Updated:** 14 November 2026  
**Project assessed:** Enhanced EarthScope dashboard package, including its historical SQLite archive and trained Cairo temperature model.

## Findings at a glance

EarthScope retains live NASA POWER Daily access and now also includes a persisted, multi-year NASA POWER archive. The SQLite database contains **333,860 daily-variable observations** for Cairo, Phoenix, Tokyo, Sydney, and Manila from **1981-01-01 through 2026-09-14**. Each of the 20 location-variable series has 16,693 daily records and no missing normalized values. Fifty original NASA response payloads are retained as compressed source files with SHA-256 provenance checks.

A trained standardized ridge-regression model estimates **Cairo’s next-day daily mean 2 m temperature (T2M)**. It was evaluated chronologically on 1,096 held-out dates from 2023 through 2025. Test MAE was 0.953 °C, RMSE 1.312 °C, and R² 0.964. Persistence MAE on the same dates was 1.043 °C. This is a statistical temperature estimate; it is not a disaster prediction or an operational weather forecast.

The dashboard now produces deterministic summaries from the selected plotted historical observations. For Cairo, an ordinary least-squares fit to annual mean T2M values gives descriptive slopes of **+0.093 °C/year for 2016–2025** and **+0.032 °C/year for 1981–2025**. These use 10 and 45 annual means respectively. They describe this NASA POWER grid-cell series and do not establish cause, impacts, or a trend in every location.

## Data and storage

The archive came from 50 live requests to the NASA POWER Daily Point API. It contains four variables per location: `T2M` in °C, `RH2M` in %, `WS10M` converted from m/s to km/h, and `PRECTOTCORR` in mm/day. Dates are daily UTC keys. The series are NASA POWER gridded estimates, not in-situ station observations. No values were interpolated or invented.

The SQLite v2 database is `data/historical/earthscope_power.sqlite3` (90,030,080 bytes in the delivered build). It stores observations, source-response provenance, ingestion runs, model versions, evaluation records, and prediction records. Natural-key constraints prevent duplicate location/dataset/variable/date/resolution records. The 50 compressed original responses total 1,485,323 bytes; their stored SHA-256 digests were verified. `PRAGMA integrity_check` returned `ok`, and `PRAGMA foreign_key_check` returned zero violations.

Migration `002_normalize_history_provenance.sql` converts the earlier v1 layout to v2 when the history store opens an older database. The ingestion script supports retries and incremental updates with a seven-day overlap. Live mode remains a bounded NASA request; historical mode queries the bundled archive and does not download the entire history on page load.

NASA references: [Daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/), [parameter dictionary](https://power.larc.nasa.gov/docs/tutorials/parameters/), and [meteorology data sources and methodology](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/).

## Temperature model and evaluation

The model is a standardized ridge regression for one daily step ahead. Its predictors are day-of-year sine and cosine, Cairo T2M lags of 1, 2, 7, 14, 30, and 365 days, and preceding 7- and 30-day means. The regularization value was selected using validation MAE, yielding alpha 0.01.

| Split | Target dates | Samples | Use |
|---|---|---:|---|
| Train | 1982-01-01–2019-12-31 | 13,879 | Fit the model; the 1981 observations supply lag history |
| Validation | 2020-01-01–2022-12-31 | 1,096 | Select alpha; MAE 0.997 °C |
| Held-out test | 2023-01-01–2025-12-31 | 1,096 | Final comparison against baselines |

On the same held-out test dates, ridge scored **MAE 0.953 °C, RMSE 1.312 °C, R² 0.964**. Persistence scored 1.043 °C MAE, 1.456 °C RMSE, and 0.955 R². Previous-year seasonal naive scored 2.297 °C MAE, 2.965 °C RMSE, and 0.815 R². These retrospective metrics do not guarantee future accuracy.

The bundled example uses archive input through 2026-09-14 and returns **28.82 °C for 2026-09-15**. The target date lies beyond the bundled observation range and has no stored observed value for verification. The chart distinguishes a model estimate from observations.

## Historical summaries and trend windows

Summary cards are computed from the exact observations plotted for the selected variables, locations, and UTC dates. They can report count, missingness, mean, median, range, first-to-last change, a descriptive linear slope, seasonal monthly comparisons, statistical outlier screens, and cross-variable associations where the selection supports them. Missing values remain missing. Summaries are descriptive and do not establish causation or hazard events.

For Cairo T2M, annual arithmetic means were computed for each complete year. A least-squares line fit across the yearly means gives **+0.093 °C/year over 2016–2025** (10 yearly values) and **+0.032 °C/year over 1981–2025** (45 yearly values). These equal-weight annual-mean slopes replace a prior daily-point slope that used a different calculation window/unit-of-analysis. Trend windows stop at 2025 so that every included year is complete; the underlying archive continues through 2026-09-14.

## What the project does and does not establish

The dashboard provides live NASA POWER requests, archived historical queries, deterministic plotted-data summaries, a saved and historically evaluated next-day Cairo temperature model, and a separately labelled simulated incident workflow. Threshold-based incident levels remain prototype rules. They are not official warnings and are not a model of disaster occurrence or impact.

The temperature model predicts only the next daily T2M value for Cairo from archived temperature history. It does not predict earthquakes, floods, fires, storms, droughts, landslides, or other disasters. It has no operational numerical-weather-prediction feed, no station-based independent validation, and no calibrated disaster-event probabilities. NASA POWER values are gridded estimates, and city-point values should not be interpreted as neighbourhood or station measurements. A one-day statistical estimate must not be presented as a current operational weather forecast.

No public deployment or emergency-service integration is claimed. Incident actions are local demonstration actions. The project depends on external browser libraries for maps and charts.

## Verification

The final automated suite passed **131 tests**. Additional checks passed for Python compilation, inline JavaScript syntax, live-database API routes, raw-file hashes, and SQLite/foreign-key integrity. The historical dashboard was exercised for Cairo from 2016-01-01 through 2025-12-31; its plotted summaries matched the summary API. The training and held-out metrics above were read from the saved model metadata generated from the historical archive.

## References

- [NASA POWER Daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/)
- [NASA POWER parameter dictionary](https://power.larc.nasa.gov/docs/tutorials/parameters/)
- [NASA POWER meteorology data sources and methodology](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/)
- [Historical data and model implementation report](../../HISTORICAL_DATA_MODEL_IMPLEMENTATION_REPORT.md)
