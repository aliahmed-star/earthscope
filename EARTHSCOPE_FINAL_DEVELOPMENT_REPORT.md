# EarthScope / GEOSTORM — Updated Development Report

**Updated:** 14 November 2026  
**Project:** Enhanced EarthScope dashboard with persisted NASA POWER history  
**Readiness:** Ready for local demonstration; not represented as an operational warning or disaster-prediction system.

## Current implementation

The project retains the original FastAPI/browser dashboard, NASA POWER live mode, map, charts, incident workflow, and optional Streamlit view. It now also includes a SQLite v2 archive, historical query/API and UI, deterministic summaries derived from plotted values, a saved Cairo temperature model with chronological validation, and migration and incremental-ingestion workflows.

## Data archive

The SQLite file at `data/historical/earthscope_power.sqlite3` contains **333,860 daily-variable observations** for Cairo, Phoenix, Tokyo, Sydney, and Manila, covering 1981-01-01 through 2026-09-14. Each of its 20 location-variable series has 16,693 daily rows and zero missing normalized values. The four variables are T2M (°C), RH2M (%), WS10M (km/h after ×3.6 conversion from m/s), and PRECTOTCORR (mm/day). The underlying NASA POWER values are daily gridded estimates, not station readings.

Fifty compressed NASA source responses are included and verified by SHA-256. The v2 schema stores daily records and normalized response provenance. Natural-key uniqueness protects against duplicate ingestion, and migration `002_normalize_history_provenance.sql` migrates an older v1 archive. Incremental updates use a seven-day overlap with bounded requests and retries.

## Trained model and historical trend summaries

A standardized ridge-regression model estimates one-day-ahead Cairo T2M. Training covers 1982–2019 (13,879 target rows), validation covers 2020–2022 (1,096 rows), and a separate held-out test covers 2023–2025 (1,096 rows). On test data, ridge scored MAE 0.953 °C, RMSE 1.312 °C, and R² 0.964. Persistence on the same dates scored MAE 1.043 °C, RMSE 1.456 °C, and R² 0.955. Previous-year seasonal naive scored MAE 2.297 °C, RMSE 2.965 °C, and R² 0.815.

From archive input through 2026-09-14, the example estimate is 28.82 °C for 2026-09-15. It is a statistical estimate and was not compared with an observed value for that target date. It is not an operational weather forecast and does not predict disasters.

For complete Cairo calendar years, least-squares slopes across annual mean T2M values are **+0.093 °C/year for 2016–2025** and **+0.032 °C/year for 1981–2025**. These descriptive slopes use one annual value per year and do not establish causality or impacts. The historical archive itself continues through 2026-09-14.

## Validation and limitations

The final test suite passed **131 tests**. Python compilation, inline JavaScript syntax, historical API and dashboard checks, raw-response hashes, and SQLite integrity checks passed. The incident workflow remains a simulated/prototype threshold feature; it is not a trained or validated disaster model. The temperature estimate applies only to Cairo T2M. There is no independent station evaluation or operational forecast input, and NASA POWER measurements represent grid cells. No production deployment is claimed.

For the full route list, model features and test metrics, schema/migration details, exact Windows PowerShell commands, and complete changed-file inventory, see `HISTORICAL_DATA_MODEL_IMPLEMENTATION_REPORT.md` and `README.md`.
