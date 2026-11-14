# EarthScope Historical Data, Model, and Summary Implementation Report

EarthScope was enhanced in a separate project copy; the preserved source project was not modified. The updated project includes the verified NASA archive, its compressed source responses, a trained model and evaluation metadata, the historical dashboard/API changes, tests, documentation, and the earlier submission deliverables.

## NASA data retrieved and stored

The ingestion used the NASA POWER Daily Point API at `https://power.larc.nasa.gov/api/temporal/daily/point`, with the RE community, JSON output, and UTC daily keys. NASA documents the daily endpoint and its time-standard options [1]. The parameter names and units were checked against NASA's parameter dictionary [2]. The response API version was `v2.10.3`.

The completed live backfill used 50 requests, each spanning no more than five calendar years. SQLite contains 333,860 observations covering 1981-01-01 through 2026-09-14 at five locations: Cairo, Phoenix, Tokyo, Sydney, and Manila. Each of the 20 location/variable series has 16,693 daily rows, with zero NULL normalized values:

- `T2M`: temperature in °C.
- `RH2M`: relative humidity in %.
- `WS10M`: wind in km/h, normalized from NASA's raw m/s with a documented ×3.6 conversion.
- `PRECTOTCORR`: corrected precipitation in mm/day.

These are NASA POWER daily grid-cell estimates, not weather-station observations. NASA's meteorology methodology describes MERRA-2 and GEOS-IT near-real-time product lineage, which can vary by parameter; response metadata is retained per source response rather than treating a single lineage label as universal [3]. No observations were interpolated or filled with invented values. The source responses retain their UTC request metadata and were individually checked against their stored SHA-256 digests.

Before the full backfill, the real Cairo 2010–2019 T2M and precipitation pipeline was validated end to end, storing 7,304 daily-variable records with 3,652 values per series and no missing values. The final archive has a 90,030,080-byte SQLite database and 50 gzipped raw JSON responses totaling 1,485,323 bytes. SQLite passed `PRAGMA integrity_check`; `PRAGMA foreign_key_check` returned zero violations.

## Storage, API, and dashboard behavior

SQLite schema version 2 stores daily measurements in `observations` and shared response provenance in `source_responses`. Each observation references its original response by `source_response_id`; SHA-256, raw-file path, and NASA response metadata are stored once per response instead of being repeated on every day/variable row. This reduced the full database from about 515 MB to about 90 MB. Migration `002_normalize_history_provenance.sql` converts a v1 archive automatically when `HistoryStore` opens it and compacts the database. Natural-key uniqueness prevents duplicate location/dataset/variable/date/resolution records. Incremental ingestion refreshes a seven-day overlap and uses bounded requests, retry/backoff for transient failures, and gzipped raw-response retention.

The application provides these routes:

- `GET /api/history/availability` reports date coverage, counts, and missingness actually stored.
- `GET /api/history/observations` queries a location, variable, inclusive date range, and daily resolution.
- `GET /api/dashboard?mode=historical` reads only the archived NASA observations and supplies the selected chart arrays.
- `GET /api/graph-summaries` returns deterministic summaries for those same plotted values.
- `GET /api/model/status` and `GET /api/model/evaluation` expose the saved model and its evaluation.
- `GET /api/predictions/next-day` returns the one-day-ahead model estimate and same-date baseline estimates.

The existing dashboard layout and interactions remain in place. Historical mode adds date controls, archive/source labels, summary cards, and a prediction panel. Summaries refresh with the selected locations and dates. The model marker is drawn separately from observations and only when the selected chart ends on the model's `as_of` date. Historical mode does not silently fall back to the simulated demo data. Ingestion and training run as finite CLI jobs; normal web requests do not ingest the archive or retrain the model.

## Trained model and held-out evaluation

The saved model is a standardized ridge regression for one-day-ahead Cairo `T2M`. Features are day-of-year sine/cosine, exact temperature lags of 1, 2, 7, 14, 30, and 365 days, and the preceding 7- and 30-day means. Missing required inputs are not imputed. The model uses a chronological split and selects its regularization alpha on validation MAE; the selected alpha was `0.01`.

Actual target-date periods and counts:

- Training: 1982-01-01 through 2019-12-31; 13,879 rows. The available 1981 values supply the prior-year lag window, so the first target row is in 1982.
- Validation: 2020-01-01 through 2022-12-31; 1,096 rows. MAE was 0.997 °C.
- Held-out test: 2023-01-01 through 2025-12-31; 1,096 rows.

On the same held-out test rows, ridge scored MAE 0.953 °C, RMSE 1.312 °C, bias -0.172 °C, and R² 0.964. Persistence scored MAE 1.043 °C, RMSE 1.456 °C, and R² 0.955. Previous-year seasonal naive scored MAE 2.297 °C, RMSE 2.965 °C, and R² 0.815. The baselines use the same test dates. These historical metrics do not guarantee future accuracy.

The active model version is `cairo-t2m-next-day-20261114T001236Z`. Its JSON artifact and training/evaluation metadata are `models/cairo_t2m_next_day.json` and `models/cairo_t2m_next_day.metadata.json`. Model-version, validation, test, and prediction records are also persisted in SQLite. The database retains two training versions, four split-evaluation rows, and two API-generated predictions from verification runs; the newest artifact is the active version.

A real API request using the newest artifact and the archive ending 2026-09-14 returned 28.8166 °C for 2026-09-15. Its same-target persistence estimate was 29.14 °C and its previous-year seasonal-naive estimate was 27.50 °C. This is a one-daily-step statistical estimate from the archive, not an operational weather forecast. Its target date is beyond the bundled observation range and was not compared with an observed target value in this project.

## Example summary from plotted observations

For Cairo from 2016-01-01 through 2025-12-31, the dashboard plotted 3,653 daily temperature values. The summary reported 100% coverage, mean 22.101 °C, median 22.73 °C, minimum 6.44 °C on 2016-01-27, maximum 35.40 °C on 2016-06-03, and a descriptive linear slope of +0.1647 °C/year. The July mean was 30.645 °C and the January mean was 12.153 °C. The text explicitly labels the slope and monthly comparison as descriptive, not causal. A single-year chart selection reports that a multi-year seasonal conclusion is unavailable. Potential outliers are an IQR statistical screen, not event labels; missing values remain omitted rather than treated as zero.

The `GET /api/graph-summaries` result was checked against the `graph_summaries` attached to the historical dashboard response for the same selected location and date range; they matched exactly.

## Verification performed

- Baseline before implementation: 94 tests passed.
- Final full suite: **131 passed** in 5.73 seconds.
- Python `compileall`: passed for the API, dashboard service, source package, and scripts.
- Node `--check`: passed for the inline JavaScript extracted from `index.html`.
- v1-to-v2 migration: tested on a staged history database and on the full archive; value queries and raw provenance remained available after migration.
- Live NASA POWER ingestion: 50/50 requests completed; every one of the 50 compressed response files matched the SHA-256 digest in SQLite.
- Real-database API checks: `/`, archive availability, archive observations, historical dashboard, graph summaries, model evaluation, and next-day prediction returned HTTP 200. Historical dashboard series contained 3,653 plotted days for the ten-year test range.
- Database integrity and foreign keys: integrity check `ok`; zero foreign-key violations.

## Windows PowerShell commands

Run from the extracted project directory. The supplied ZIP already includes the archive, raw responses, and trained model; you do not need to repeat the initial download. If script activation is blocked by the current PowerShell execution policy, use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` for that terminal session.

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

Open `http://127.0.0.1:8000/`. If starting with an empty database instead of the supplied archive, run this first, then train and test as above:

```powershell
python scripts\ingest_nasa_power_history.py --start-date 1981-01-01 --end-date 2026-09-14
```

For later incremental refreshes, run `python scripts\ingest_nasa_power_history.py --update`. It refreshes an overlapping seven-day tail and uses the conservative recent-data cutoff. If port 8000 is already occupied, start with `--port 8001` and open `http://127.0.0.1:8001/`.

## Limitations

NASA POWER data are gridded daily estimates, not station observations, and the archive has not been independently validated against NOAA station records. The saved statistical model covers only Cairo daily temperature and has no uncertainty interval or operational forecast input. Its prediction is not an authoritative weather forecast. Hazard thresholds and incident workflows remain prototype features; incident state is in memory. The summaries describe the selected plotted data and do not establish causality or event significance. The browser still depends on its existing public chart/map CDN libraries. The project was tested locally; no public deployment was made.

## Complete file inventory

Eight existing project files changed relative to the preserved source copy:

- `.gitignore`
- `README.md`
- `api.py`
- `dashboard_service.py`
- `docs/architecture.md`
- `docs/dataset_sources.md`
- `index.html`
- `src/earthscope/config.py`

The following project files were added:

- `data/historical/earthscope_power.sqlite3`
- `data/migrations/001_historical_archive.sql`
- `data/migrations/002_normalize_history_provenance.sql`
- `models/cairo_t2m_next_day.json`
- `models/cairo_t2m_next_day.metadata.json`
- `scripts/ingest_nasa_power_history.py`
- `scripts/train_temperature_model.py`
- `src/earthscope/graph_summaries.py`
- `src/earthscope/history_ingest.py`
- `src/earthscope/history_store.py`
- `src/earthscope/prediction_model.py`
- `tests/test_graph_summaries.py`
- `tests/test_historical_api.py`
- `tests/test_history_store.py`
- `tests/test_prediction_model.py`
- `HISTORICAL_DATA_MODEL_IMPLEMENTATION_REPORT.md` (this report)

The ZIP also includes the 50 original NASA POWER responses at `data/raw/nasa_power_history/`:

- Cairo: `cairo-eg_19810101_19851231_559539f23e65d0aa.json.gz`, `cairo-eg_19860101_19901231_31c30f97890e276e.json.gz`, `cairo-eg_19910101_19951231_4e28bc80f009160c.json.gz`, `cairo-eg_19960101_20001231_b8dff8159438e96e.json.gz`, `cairo-eg_20010101_20051231_1d423a5f6eabb257.json.gz`, `cairo-eg_20060101_20101231_85b9271f78ffc378.json.gz`, `cairo-eg_20110101_20151231_f18b57fb37e6abef.json.gz`, `cairo-eg_20160101_20201231_f5a18d37b0fb2973.json.gz`, `cairo-eg_20210101_20251231_74e6f9598121ae5d.json.gz`, `cairo-eg_20260101_20260914_a416a001c909dc58.json.gz`.
- Manila: `manila-ph_19810101_19851231_a422a52eee1a7530.json.gz`, `manila-ph_19860101_19901231_d219f45ec23b7d0c.json.gz`, `manila-ph_19910101_19951231_b01d08e6990f8dea.json.gz`, `manila-ph_19960101_20001231_d46e4b4c2b73294a.json.gz`, `manila-ph_20010101_20051231_237d2b6508e5daa9.json.gz`, `manila-ph_20060101_20101231_7c851998c50da2dc.json.gz`, `manila-ph_20110101_20151231_6b5cf6c001b9eaf7.json.gz`, `manila-ph_20160101_20201231_6cb0daaf22e61ad5.json.gz`, `manila-ph_20210101_20251231_c13af17044fb7afb.json.gz`, `manila-ph_20260101_20260914_6eb836e2f870b2a8.json.gz`.
- Phoenix: `phoenix-us_19810101_19851231_482dcdb2d4a8de5f.json.gz`, `phoenix-us_19860101_19901231_2a99c6f693dd4ff9.json.gz`, `phoenix-us_19910101_19951231_bf6da43e905fca05.json.gz`, `phoenix-us_19960101_20001231_181b76ac936e942d.json.gz`, `phoenix-us_20010101_20051231_1c77f7aa6689d7eb.json.gz`, `phoenix-us_20060101_20101231_e9485295405c9afc.json.gz`, `phoenix-us_20110101_20151231_d6db1d31ed02191f.json.gz`, `phoenix-us_20160101_20201231_aec52e9b84fd9417.json.gz`, `phoenix-us_20210101_20251231_582030f76ef54be1.json.gz`, `phoenix-us_20260101_20260914_a37cd576d4d00f25.json.gz`.
- Sydney: `sydney-au_19810101_19851231_fdc3e761400553bc.json.gz`, `sydney-au_19860101_19901231_c312afb6456f0a75.json.gz`, `sydney-au_19910101_19951231_e25d17e2417e3c07.json.gz`, `sydney-au_19960101_20001231_9e78c524112dc326.json.gz`, `sydney-au_20010101_20051231_aff29f477b38f0c6.json.gz`, `sydney-au_20060101_20101231_29c262e59680d54d.json.gz`, `sydney-au_20110101_20151231_42eb673626e434d4.json.gz`, `sydney-au_20160101_20201231_16ea276e27c56e73.json.gz`, `sydney-au_20210101_20251231_97174cc81de8a345.json.gz`, `sydney-au_20260101_20260914_0ed08dd4319ef990.json.gz`.
- Tokyo: `tokyo-jp_19810101_19851231_e93a165fa44a293d.json.gz`, `tokyo-jp_19860101_19901231_3e04be64a82fd976.json.gz`, `tokyo-jp_19910101_19951231_824840e0a33043bc.json.gz`, `tokyo-jp_19960101_20001231_b4eba4309a29ed75.json.gz`, `tokyo-jp_20010101_20051231_1bd608433b5d3d8e.json.gz`, `tokyo-jp_20060101_20101231_7cdd2b74fbd3ab10.json.gz`, `tokyo-jp_20110101_20151231_8af3024e78aecc25.json.gz`, `tokyo-jp_20160101_20201231_f593d5e40243dbd4.json.gz`, `tokyo-jp_20210101_20251231_605837dac5f29f58.json.gz`, `tokyo-jp_20260101_20260914_f5191bd36547c4de.json.gz`.

No source project files were removed. The previous submission assets remain in `submission_deliverables_2026-11-14/`.

## References

[1]: https://power.larc.nasa.gov/docs/services/api/temporal/daily/ "NASA POWER Daily API Documentation"
[2]: https://power.larc.nasa.gov/docs/tutorials/parameters/ "NASA POWER Parameter Dictionary Documentation"
[3]: https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/ "NASA POWER Meteorology Data Sources Methodology"
