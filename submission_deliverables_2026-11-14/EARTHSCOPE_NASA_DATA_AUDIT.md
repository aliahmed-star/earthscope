# EARTHSCOPE NASA Data Audit

**Audit date:** 14 November 2026  
**Project examined:** `/home/ubuntu/EARTHSCOPE_working/merged`  
**Scope:** Current FastAPI/browser dashboard, optional Streamlit view, active and legacy source code, local JSON data, tests and public 2026 NASA Space Apps submission guidance.

## Judge-ready summary

EarthScope’s only active NASA data integration is the **NASA POWER Daily API**, requested at selected coordinates for four daily meteorological parameters: 2 m temperature (`T2M`), 2 m relative humidity (`RH2M`), 10 m wind speed (`WS10M`) and corrected precipitation (`PRECTOTCORR`). The dashboard converts wind from m/s to km/h, preserves missing values, validates each response and displays the returned daily series on a map, in a table and in four charts. In a live smoke check on 14 November 2026, the app successfully requested two UTC dates for Cairo, Phoenix and Tokyo: six transient location-day records across four variables. That is one bounded API response, not a stored archive total.

The repository’s saved NASA snapshots contain 17 processed rows, but five duplicate the same five location-day keys for 1 January 2024. After deduplication, there are **12 unique NASA location-day records** from five locations on only three dates. A separate seven-row file is explicitly simulated demo data. The current source is enough to demonstrate an honest, explainable prototype; it is not enough to validate operational hazard warnings, forecasts, local disaster impacts or climate trends. **No database is present.** Live responses and incident state are transient in memory; only the demo file and historical NASA JSON snapshots are durable project files. NASA POWER supplies the required NASA data source for a project submission, but this does not guarantee any award or judging outcome. [1] [2] [6]

## Active and inactive data sources

### Integrated NASA source: NASA POWER Daily

The active provider in `src/earthscope/providers/nasa_power.py` calls NASA’s temporal Daily point endpoint, `https://power.larc.nasa.gov/api/temporal/daily/point`. It sends an unauthenticated HTTP GET with JSON format, the `RE` community, a coordinate, an inclusive date range, the four variables below, and `time-standard=UTC`. The code uses a 15-second request timeout and does not send an API key. NASA POWER documents daily time-series access from 1981-01-01 to near real time; data availability, latency and source resolution depend on the product and parameter. [1] [2] [4]

The data are daily gridded environmental products, not four raw satellite measurements or in-situ weather-station readings. NASA’s meteorology methodology describes a MERRA-2 / GEOS-IT source history and a native meteorological grid of 0.5° latitude by 0.625° longitude. POWER’s parameter documentation should be used for parameter-specific lineage; a response-level `sources` list is not enough to claim that every field for every date came from one named sensor or model. The daily API retains original source resolution. The model grid and the returned coordinate do not make this a local station observation. [1] [2] [3] [4]

**Parameters requested and application mappings:**

- **`T2M` — Temperature at 2 Meters.** NASA metadata describes average air temperature at 2 m in °C. EarthScope stores it unchanged as `temperature_c`. It supports display and prototype temperature-threshold rules. [2]
- **`RH2M` — Relative Humidity at 2 Meters.** NASA metadata gives percent relative humidity. EarthScope stores it as `humidity_pct` and uses it in display and the combined wildfire-favourable rule. [2]
- **`WS10M` — Wind Speed at 10 Meters.** NASA reports m/s. EarthScope multiplies by 3.6 and rounds to two decimals for `wind_speed_kmh`. It supports display and prototype wind rules. This conversion is a unit conversion, not a forecast or exposure-height adjustment. [2]
- **`PRECTOTCORR` — Precipitation Corrected.** NASA metadata describes bias-corrected total precipitation at the surface in mm/day. EarthScope stores it as `rainfall_mm` and displays it as a daily amount. It is not a gauge-verified rolling 24-hour total. [2] [4]

NASA documents daily frequency and near-real-time access. Its meteorological methodology notes the MERRA-2 to GEOS-IT series splice and recent-data latency; NASA advises ending climate-trend analyses about two months behind near real time because the newest source segment differs from the earlier record. EarthScope’s default end date is two days before the current date, which is a practical request boundary for recent dashboard exploration, **not** a climate-trend-quality cutoff. [1] [3] [4]

### Other source classifications

- **Saved NASA-origin snapshots:** Three raw responses in `data/raw/` and three normalized exports in `data/processed/` were examined. These are stored examples derived from NASA POWER, not the source read by the current live dashboard route.
- **Simulated demonstration data:** `data/processed/demo_observations.json` contains seven explicit simulated rows dated 2026-11-13. The dashboard uses this file in demo mode and as a labelled fallback when a live request fails or yields no valid observations.
- **Test fixtures:** NASA-like payloads in tests are deterministic fixtures and do not add to the available NASA observation total. Tests mock network responses.
- **Legacy synthetic code:** `mock_data.py` defines five example incidents and can generate 120 synthetic four-hourly measurements if called. It is not imported by the active `api.py` / `index.html` dashboard flow and is not a stored NASA dataset.
- **NOAA:** NOAA Climate Data Online is mentioned as an evaluated candidate only. No NOAA client, token, station match or NOAA observations are integrated. NOAA is not NASA data. [15]
- **Other proposed NASA services:** NASA Earthdata, AppEEARS, Giovanni, GPM IMERG and FIRMS are not integrated; no working client or active data pipeline for them was found.
- **Map tiles:** The browser dashboard’s dark basemap is served by CARTO, with OpenStreetMap attribution visible in the rendered map. MapLibre/deck.gl and Chart.js are interface libraries, not NASA data sources.
- **NASA image in these deliverables:** The cover illustration is NASA’s 2002 Blue Marble image, used only as contextual imagery with credit. It is not a live map, an EarthScope data layer or an additional application data integration. NASA imagery must not imply agency endorsement, and NASA’s protected insignia/logotype are not used. [7] [8]

## Data quantity and coverage

### Persisted NASA sample files

The local NASA sample consists of three raw JSON snapshots and three processed JSON snapshots:

- Raw files total **19,649 bytes** and contain 12 location response payloads across the files.
- Processed NASA files total **8,657 bytes** and contain **17 stored rows**: 5 rows for 2024-01-01; 10 rows for 2024-01-01 through 2024-01-02; and 2 rows for 2024-07-15.
- The two January exports overlap on five location-day keys. Deduplicating by `(location_id, UTC date)` leaves **12 unique records**, with **zero conflicting duplicate keys**.
- Those records cover five locations—Cairo, Phoenix, Tokyo, Sydney and Manila—on only **three dates**: 2024-01-01, 2024-01-02 and 2024-07-15. The first-to-last dates are 196 elapsed days apart; they are not a continuous time series.
- Each of the 12 unique rows has all four normalized values present: **12 valid values per variable, 48 non-null measurement cells in total**. The 17 stored rows include duplicate exports and must not be summed as 17 independent NASA observations.

The sample files therefore show limited snapshots, not a complete history, a fixed sample of all NASA POWER data, or a count of what the API can return today.

### Simulated sample

The separate demo JSON file is **2,757 bytes** and contains seven unique location-day records, all dated 2026-11-13. Its seven locations are Cairo, Phoenix, Tokyo, Sydney, Manila, Reykjavik and Nairobi. It contains seven non-null temperatures, seven humidities, six wind measurements and seven daily precipitation values. Nairobi has a deliberately missing wind value. All rows are marked simulated; none should be counted as real NASA or NOAA observations.

Across the six data JSON files, the stored data total **31,063 bytes**: 28,306 bytes of NASA raw-plus-processed snapshots and 2,757 bytes of simulation data. These file-size totals exclude source code, screenshots and runtime memory.

### Live runtime check

A new bounded smoke test through the running app on 14 November 2026 returned HTTP 200 in live mode for Cairo, Phoenix and Tokyo over 2026-11-07 to 2026-11-08. It returned two UTC date keys for each of three locations, or **six location-day slots across four variables**. The response identified `POWER Daily API` v2.10.3 and response-level source labels `GEOSIT` and `POWER`; it did not include fallback notes and was marked non-simulated. The response was served from the NASA route and its live cache, not persisted as a permanent archive. This single request is a runtime smoke check, not a total API observation count, independent validation or proof of availability at all locations and dates.

### Location and request scope

The live provider defines five default coordinate points. The browser dashboard initially selects three of them (Cairo, Phoenix and Tokyo); users can select the other two. The demo adds Reykjavik and Nairobi, so the station selector can show seven locations across both modes. The default live date interval is 14 days ending two days before today; the service caps a request at 31 inclusive calendar days. It fetches selected point requests concurrently, up to five workers. Matching live responses are held in a process-memory cache for ten minutes, with a maximum of 128 entries. No API total is inferred from those limits.

## How the application processes and uses data

The primary browser flow is `index.html` → FastAPI routes in `api.py` → `dashboard_service.build_dashboard()` → NASA POWER requests → normalization and validation → deterministic risk assessment → incident registration → one JSON payload to the interface. Map markers, the latest-reading table and four charts use the same dashboard response. Map tiles are an independent CARTO service.

For NASA payloads, `normalize_nasa_power_records()` collects daily date keys, serializes each date as midnight UTC for the shared date-index contract, converts `WS10M` from m/s to km/h by multiplying by 3.6, rounds wind and corrected precipitation to two decimals, preserves response metadata, and marks rows non-simulated. NASA fill values such as `-999`, non-finite numbers and malformed values become `None`; missing is never converted to zero. The shared loader normalizes timezone-aware timestamps, checks coordinate/value ranges and required fields, rejects malformed records, and records rejection details. When locations have different missing days, the service aligns the time series to a shared UTC date index and leaves absent values `null`.

The configured hazard logic is a deterministic rule system in `src/earthscope/config.py`, not a statistical model. Heat thresholds are 35/40/45 °C; cold thresholds are −10/−20/−30 °C; wind thresholds are 50/90/120 km/h; daily-rain thresholds are 50/100/150 mm/day. Wildfire-favourable conditions require all three variables at each tier: temperature at least 30/35/40 °C, relative humidity at most 30/20/15%, and wind at least 30/40/50 km/h. The highest triggered tier is selected, and a stable configuration order breaks ties. Missing inputs are disclosed and cannot silently become zero. The code labels the thresholds `prototype-v1`; its disclaimer explicitly says they are not official meteorological warnings or validated disaster predictions.

The browser map renders selected coordinates as risk-colored circles with click-to-zoom behavior. Chart.js shows temperature, humidity and wind as line charts and precipitation as a bar chart. Risk labels and incidents are outputs of the configured rules. The dashboard does not calculate forecast probabilities, climate anomalies, flood depth, fire spread, or health impacts.

## Storage, cache and database status

**No database is present.** The project contains no SQLite or other database file, SQL schema, migration, relational table or seed script. No database driver or connection appears in the active data path.

Storage currently consists of:

- **NASA samples:** Static JSON files under `data/raw/` and `data/processed/`. They are retained historical examples, not read by the active live request route.
- **Demo observations:** A local JSON file under `data/processed/demo_observations.json`, read in demo mode and as an explicit fallback.
- **Live NASA observations:** Retrieved on demand and normalized in process memory. The `dashboard_service` response cache is bounded by ten minutes and 128 entries. It is not a durable observation store. The live route does not pass output directories to the NASA provider’s optional JSON writer.
- **Incidents:** Two process-memory `IncidentStore` instances keep live-mode and demo-mode incident state separate. They reset on process restart. Configuration names an optional `data/processed/incidents.json` path, and `incidents.py` supports JSON persistence if explicitly enabled; `PERSIST_INCIDENTS` is currently `False`, so that path is inactive by default. There are no relational incident tables.
- **Browser state:** Current selections and chart/map objects are held by the page’s JavaScript state. No browser local-storage or IndexedDB persistence was found.

If the live service fails for every selected point or returns no usable observations, the loader uses the local simulation and the response/UI identifies demo mode. Partial failures can leave usable live records with failure notes. The dashboard depends on public CDN assets for its map and charts; the screenshot capture in this audit recorded a blocked external Mapbox CSS request, even though the simulated-mode basemap rendered. In the live screenshot, the chart/table displayed and the API returned live records, but the map pane remained blank in that particular headless capture. This capture limitation is recorded rather than represented as a successful live-map visual check.

The standard dashboard is same-origin. Optional CORS configuration only permits explicitly configured origins, but the API does not implement authentication or authorization for incident actions. CORS is not an authentication control. If the app is publicly deployed, write actions and process-local state require a security and operational review. No deployment or production-readiness claim is made.

## Data sufficiency conclusion

**Conclusion: sufficient for the current demonstration prototype, with substantial limits; insufficient for operational warnings or scientifically validated local hazard conclusions.**

The active API can provide daily global gridded weather values at a small set of configurable coordinates, and the app demonstrates source labeling, unit normalization, missing-value handling, multi-location comparison, rules-based explanations and a simulated incident workflow. The bounded live smoke test and the saved snapshots confirm that the integration can return the expected variables and flow through the interface. The 12 unique saved NASA rows are enough to test basic parsing and illustrate the data contract, but not enough to characterize seasons, compare years, establish thresholds or validate a hazard event.

The implemented rules only indicate whether a downloaded daily value crosses a project-defined threshold. They do not establish a future risk, official warning, causal relationship or actual local disaster. The system has no independent station-validation set, forecasts, exposure/vulnerability data, event labels, historical baseline, vegetation/fuel condition, hydrologic model or impact observations. The current dataset is therefore sufficient to show a transparent data-processing prototype, but not to claim that EarthScope predicts or validates real-world hazards.

**Is more NASA data needed now?** Not simply to increase record count, and not for the minimum NASA-data element described by the official 2026 guide: EarthScope already uses NASA POWER Daily. More data become useful only after the intended hazard and decision are specified. Better temporal coverage, field-level validation and product matching are more important than adding several unrelated APIs. NASA’s guide requires teams to state which NASA data/resources they used for a Global Award submission; it does not guarantee eligibility from this audit alone. [6]

**Potential additions tied to concrete research needs:**

- NASA GPM IMERG Final daily precipitation could support a product-to-product precipitation comparison or broader precipitation context. NASA describes IMERG as a multi-satellite precipitation estimate with different Early/Late/Final runs; Final is the research-oriented run. The Version 07 daily catalog describes a global 0.1° daily product over 2000–2024 as listed when checked. Its rate/amount conventions and product timing must be reconciled before comparing it with POWER `PRECTOTCORR`; it is not an automatic drop-in. [13] [14]
- NASA FIRMS MODIS/VIIRS active-fire detections could corroborate observed fire detections for selected dates and locations. They are evidence of detections, not wildfire-risk forecasts. FIRMS web services require a free MAP_KEY and impose transaction limits; NASA’s page also advises users that Suomi NPP data delivery ceased in November 2026, requiring attention to NOAA-20/NOAA-21 product alternatives. Any integration should use secure credential storage and document product choice and detection limits. [10] [11] [12]
- If EarthScope adds climate-trend analysis, use longer consistent historical data and apply NASA’s near-real-time cutoff guidance. Validation against a carefully selected independent station dataset may be more valuable than adding another NASA product. NOAA CDO is one possible external, non-NASA reference; its API uses a token and requires an explicit station/time/spatial matching plan. [3] [15]

## 2026 submission implications

The official 2026 Project Submission Guide, dated 13 November 2026, requires either a public external video link of **30 seconds or less** or a public external slide-demo link of **up to seven slides, including title and intro**. The demo and project-page content must be in English; other-language video needs English subtitles. NASA will not accept video or document uploads directly. The guide calls for a project demonstration and specific NASA data/resource details; it lists team name, members’ names and selected challenge in the slide-demo tips. The supplied repository contains no verified team name, team-member names or selected challenge title, so those details must be supplied by the team if required in the final submission. A team photograph is not required by the guide. [6]

The project’s inline SVG in `index.html` is an EarthScope mark, not a standalone logo asset and not NASA branding. The NASA Blue Marble asset used in these deliverables is credited as contextual NASA imagery. NASA media guidance requires factual use, source acknowledgement and no implied NASA endorsement; the NASA insignia/logotype are not used. [7] [8]

If AI-generated narration is used, the guide requires an acknowledgement in descriptive text and metadata. The completed demo package therefore identifies the narration as AI-generated in its visible text and media metadata; the public-hosting description should retain that disclosure. No AI-generated team image or simulated dashboard will be used. [6]

## References

[1]: https://power.larc.nasa.gov/docs/services/api/temporal/daily/ "NASA POWER Daily API Documentation"
[2]: https://power.larc.nasa.gov/docs/tutorials/parameters/ "NASA POWER Parameter Dictionary"
[3]: https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/ "NASA POWER Meteorology Data Sources and Methodology"
[4]: https://power.larc.nasa.gov/docs/faqs/data/ "NASA POWER Data FAQs"
[5]: https://power.larc.nasa.gov/docs/referencing/ "NASA POWER Referencing Guide"
[6]: https://www.spaceappschallenge.org/resources/project-submission-guide/ "NASA Space Apps Challenge Project Submission Guide 2026"
[7]: https://www.nasa.gov/nasa-brand-center/images-and-media/ "NASA Images and Media Usage Guidelines"
[8]: https://science.nasa.gov/earth/earth-observatory/the-blue-marble-true-color-global-imagery-at-1km-resolution/ "NASA Earth Observatory Blue Marble 2002"
[9]: https://wmo.int/publication-series/state-of-global-climate/state-of-global-climate-2025 "WMO State of the Global Climate 2025"
[10]: https://www.earthdata.nasa.gov/data/tools/firms "NASA Earthdata FIRMS"
[11]: https://www.earthdata.nasa.gov/data/tools/firms/faq "NASA FIRMS Frequently Asked Questions"
[12]: https://firms.modaps.eosdis.nasa.gov/api/map_key/ "NASA FIRMS MAP_KEY"
[13]: https://gpm.nasa.gov/data/imerg "NASA Global Precipitation Measurement IMERG"
[14]: https://www.earthdata.nasa.gov/dashboard/data-catalog/GPM_3IMERGDF.v07 "NASA Earthdata GPM IMERG V07 Final Daily Catalog"
[15]: https://www.ncei.noaa.gov/cdo-web/webservices/v2 "NOAA Climate Data Online Web Services API v2"
