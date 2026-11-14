# EarthScope data-source registry

Status checked: 2026-11-14. This registry distinguishes integrated sources from candidates. A candidate is not an integration.

## Integrated: NASA POWER Daily API

**Status:** Integrated and live-request verified. The application calls the NASA POWER temporal daily point endpoint from `src/earthscope/providers/nasa_power.py`. Requests use the Renewable Energy (`RE`) community, JSON, the selected coordinate and date range, and explicitly request `time-standard=UTC`. NASA's Daily API supports daily time-series responses and documents UTC and Local Solar Time as available time standards; the daily service defaults to Local Solar Time unless a time standard is supplied. The API documentation describes daily availability from 1981 to near real time and notes that parameter products retain their original source spatial resolution. No single grid resolution or fixed publication delay is claimed here because the source resolution and data availability depend on the parameter and product. [1]

The integrated parameters and canonical mappings are:

- `T2M` — Temperature at 2 Meters, degrees Celsius → `temperature_c` (°C).
- `RH2M` — Relative Humidity at 2 Meters, percent → `humidity_pct` (%).
- `WS10M` — Wind Speed at 10 Meters, metres per second → `wind_speed_kmh` (km/h), multiplied by 3.6.
- `PRECTOTCORR` — Precipitation Corrected, millimetres per day → `rainfall_mm` (mm/day), retained as a daily amount.

The labels and units above match the NASA POWER response's `parameters` metadata observed during the live verification request and NASA's parameter dictionary guidance. The app does not interpret the API's daily values as instantaneous measurements or as instrumented weather-station readings. `observed_at` records the UTC daily date key at midnight as a date index, not the instant at which all daily measurements occurred. Missing/fill values, including `-999`, become `None`; non-finite numbers are rejected. [1] [2]

**Access and limitations:** The integration performs an HTTP GET and sends no API token. A bounded 15-second request timeout is used. NASA POWER's response metadata is retained for API name/version, time standard, community when supplied, source labels, and parameter names/units. The `sources` values returned in the sample (`GEOSIT`, `POWER`) are recorded as API metadata; they are not treated as a complete lineage statement for every parameter. The NASA POWER parameter dictionary describes the service's parameters as drawing on satellite-derived solar-radiation observations and meteorological assimilation models, and directs users to inspect data sources per parameter. Do not generalize one underlying model or satellite product to all variables. [2]

**Verification performed:** On 2026-11-14, an unauthenticated request to the official point endpoint for Cairo coordinates and 2026-11-07 through 2026-11-08 returned HTTP 200. The response declared UTC, included all four requested parameter keys, and returned two daily keys for each. A follow-up request returned NASA's response metadata with the four long names and units, API name/version, fill value, and source labels. These were bounded smoke checks, not a validation of NASA POWER values against independent station observations.

**Historical archive actually stored:** On 2026-11-14, the ingestion script completed 71 requests of at most five calendar years each, using NASA POWER API response version `v2.10.3`. SQLite contains **446,364 rows across 12 locations in 12 countries**:

| Locations | Stored dates | Days per series | Complete shared years |
|---|---|---|---|
| Cairo, Phoenix, Tokyo, Sydney, Manila | 1981-01-01 – 2026-09-14 | 16,693 | 45 (1981–2025) |
| Delhi, Jakarta, London, Nairobi, Reykjavík, São Paulo, Toronto | 2015-01-01 – 2025-12-31 | 4,018 | 11 (2015–2025) |

Each location stores all four parameters. Every one of the 48 series has zero NULL normalized values. A location qualifies for country-level comparison only when it has at least ten shared complete calendar years in which all 365/366 days are valid for all four variables; all 12 locations qualify. The 71 original JSON responses are retained as gzip files with SHA-256 digests over the decompressed payload and request metadata; the database is 123,293,696 bytes and the compressed raw files total 1,995,885 bytes. Schema version 3 adds country name and ISO country code per location (migration `003_location_country_metadata.sql`), on top of the normalized response-level provenance introduced by migration 002. A prior real Cairo 2010–2019 T2M/PRECTOTCORR ingestion verified a smaller end-to-end pipeline run before the expansion. This is API/pipeline verification, not independent station validation or an assessment of scientific accuracy. NASA's [meteorology methodology](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/) describes MERRA-2 reanalysis and GEOS-IT near-real-time lineage for the meteorology products; the archive preserves the source labels and metadata returned per response because lineage may vary by parameter. [1] [2] [5]

**Official references:** [Daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) [1] and [Parameter Dictionary documentation](https://power.larc.nasa.gov/docs/tutorials/parameters/) [2].

NASA POWER's referencing guide asks users of POWER products to include the POWER project reference and data reference, including the service name, service version, and access date. The dashboard displays the response's service/version and retrieval timestamp; publications and redistribution should follow NASA's [official referencing guide](https://power.larc.nasa.gov/docs/referencing/) [4].

## Evaluated candidate: NOAA Climate Data Online

**Status:** Not integrated. NOAA CDO v2 exposes dataset, datatype, station, and observation endpoints. This could add ground-station observations for a carefully matched comparison with NASA POWER's gridded daily products. Such a comparison needs documented station selection, units, observation timing, and spatial/temporal matching; similar field names alone are not sufficient.

NOAA's official documentation requires an access token in the request header and states a limit of five requests per second and 10,000 requests per day per token. No NOAA token was supplied for this project, and the repository has no station-mapping or comparison method. The source is therefore documented as an evaluated candidate, not represented as working or used by the dashboard. [3]

**Official reference:** [NOAA Climate Data Online Web Services API v2](https://www.ncei.noaa.gov/cdo-web/webservices/v2) [3].

## Not integrated

NASA Earthdata, AppEEARS, Giovanni, SWOT, and GPM IMERG are not integrated in the merged application. There are no clients, credentials, job workflows, or sample outputs for them in this prototype. Adding one would require selecting a concrete product and documenting its access, variables, temporal and spatial support, units, licensing/attribution, and validation method before implementation. The existing prototype's scope is daily meteorological hazard demonstration; additional feeds are not added solely to increase API count.

## References

[1]: https://power.larc.nasa.gov/docs/services/api/temporal/daily/ "NASA POWER Daily API Documentation"
[2]: https://power.larc.nasa.gov/docs/tutorials/parameters/ "NASA POWER Parameter Dictionary Documentation"
[3]: https://www.ncei.noaa.gov/cdo-web/webservices/v2 "NOAA Climate Data Online Web Services API v2 Documentation"
[4]: https://power.larc.nasa.gov/docs/referencing/ "NASA POWER Referencing Guide"
[5]: https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/ "NASA POWER Meteorology Data Sources Methodology"
