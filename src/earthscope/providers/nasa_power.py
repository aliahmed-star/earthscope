"""
nasa_power.py - NASA POWER API client and observation provider for EARTHSCOPE.

OFFICIAL DOCUMENTATION
    https://power.larc.nasa.gov/docs/services/api/temporal/daily/

CAPABILITY & PARAMETERS
    Fetches daily meteorological and solar parameters via NASA POWER Daily API:
      - T2M: Temperature at 2 Meters (degrees Celsius) -> temperature_c
      - RH2M: Relative Humidity at 2 Meters (%) -> humidity_pct
      - WS10M: Wind Speed at 10 Meters (m/s) -> converted to km/h (* 3.6) -> wind_speed_kmh
      - PRECTOTCORR: Precipitation Corrected (mm/day) -> rainfall_mm (daily accumulated)

FILL VALUE HANDLING
    NASA POWER returns -999.0 (or -999) when data is missing or unavailable.
    Missing values are converted to None (NEVER 0, adhering to data_loader principles).

OFFLINE / FALLBACK PRINCIPLE
    If network access fails, times out, or returns non-200 responses, exceptions
    are caught and documented, enabling safe fallback to offline datasets without
    crashing the application.
"""

import json
import math
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default configured monitoring stations for real data retrieval
DEFAULT_LOCATIONS = [
    {
        "location_id": "cairo-eg",
        "location_name": "Cairo, Egypt",
        "latitude": 30.0444,
        "longitude": 31.2357,
    },
    {
        "location_id": "phoenix-us",
        "location_name": "Phoenix, USA",
        "latitude": 33.4484,
        "longitude": -112.0740,
    },
    {
        "location_id": "tokyo-jp",
        "location_name": "Tokyo, Japan",
        "latitude": 35.6762,
        "longitude": 139.6503,
    },
    {
        "location_id": "sydney-au",
        "location_name": "Sydney, Australia",
        "latitude": -33.8688,
        "longitude": 151.2093,
    },
    {
        "location_id": "manila-ph",
        "location_name": "Manila, Philippines",
        "latitude": 14.5995,
        "longitude": 120.9842,
    },
]

NASA_POWER_BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
TARGET_PARAMETERS = ["T2M", "RH2M", "WS10M", "PRECTOTCORR"]
FILL_VALUES = {-999.0, -999, -99.0, -99}


class NasaPowerError(RuntimeError):
    """Raised when NASA POWER API request fails, times out, or returns invalid payload."""
    pass


def fetch_nasa_power_point(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    parameters: Optional[List[str]] = None,
    community: str = "RE",
    timeout: int = 15,
    user_agent: str = "EARTHSCOPE-Client/1.0",
) -> Dict[str, Any]:
    """
    Fetch raw JSON data from NASA POWER temporal daily endpoint for a single coordinate.
    
    start_date, end_date format: 'YYYYMMDD' (e.g. '20240101')
    """
    params = TARGET_PARAMETERS if parameters is None else parameters
    query_params = {
        "parameters": ",".join(params),
        "community": community,
        "longitude": f"{longitude:.4f}",
        "latitude": f"{latitude:.4f}",
        "start": start_date,
        "end": end_date,
        # NASA POWER daily requests default to Local Solar Time. The shared
        # EARTHSCOPE observation contract stores UTC day keys, so request UTC
        # explicitly rather than labelling LST records as UTC.
        "time-standard": "UTC",
        "format": "JSON",
    }
    url = f"{NASA_POWER_BASE_URL}?{urllib.parse.urlencode(query_params)}"

    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise NasaPowerError(f"NASA POWER API returned HTTP status {response.status}")
            raw_bytes = response.read()
            return json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        if isinstance(exc, NasaPowerError):
            raise
        raise NasaPowerError(f"Failed to query NASA POWER API: {exc}") from exc


def clean_measurement(value: Any) -> Optional[float]:
    """
    Convert raw API parameter value to float, filtering out NASA POWER fill values (-999).
    Never converts missing values to 0.
    """
    if value is None:
        return None
    try:
        fval = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(fval) or fval in FILL_VALUES or fval < -900:
        return None
    return fval


def normalize_nasa_power_records(
    raw_payload: Dict[str, Any],
    location_id: str,
    location_name: str,
    latitude: float,
    longitude: float,
) -> List[Dict[str, Any]]:
    """
    Transform a NASA POWER raw JSON response into a list of standardized EARTHSCOPE observation dicts.
    
    Unit conversions:
      - T2M (°C) -> temperature_c (°C, unchanged)
      - RH2M (%) -> humidity_pct (%, unchanged)
      - WS10M (m/s) -> wind_speed_kmh (km/h, multiplied by 3.6)
      - PRECTOTCORR (mm/day) -> rainfall_mm (mm/day, unchanged)
    """
    if not isinstance(raw_payload, dict):
        raise NasaPowerError("NASA POWER response must be a JSON object.")
    properties = raw_payload.get("properties")
    if not isinstance(properties, dict):
        raise NasaPowerError("NASA POWER response is missing its properties object.")
    parameter_data = properties.get("parameter")
    if not isinstance(parameter_data, dict) or not parameter_data:
        raise NasaPowerError("NASA POWER response is missing parameter data.")
    header = raw_payload.get("header", {})
    header = header if isinstance(header, dict) else {}
    response_time_standard = header.get("time_standard")
    if response_time_standard is not None and str(response_time_standard).upper() != "UTC":
        raise NasaPowerError(
            f"Expected NASA POWER UTC daily data, received {response_time_standard!r}."
        )
    api_info = header.get("api", {})
    api_info = api_info if isinstance(api_info, dict) else {}
    source_products = header.get("sources", [])
    if not isinstance(source_products, list):
        source_products = []
    response_parameters = raw_payload.get("parameters", {})
    if not isinstance(response_parameters, dict):
        response_parameters = {}
    source_metadata = {
        "api_name": api_info.get("name"),
        "api_version": api_info.get("version"),
        "time_standard": header.get("time_standard"),
        "community": header.get("community"),
        "source_products": [item for item in source_products if isinstance(item, str)],
        "parameters": {
            name: {
                key: value
                for key, value in response_parameters.get(name, {}).items()
                if key in ("longname", "units") and isinstance(value, str)
            }
            for name in TARGET_PARAMETERS
            if isinstance(response_parameters.get(name), dict)
        },
    }
    t2m_dict = parameter_data.get("T2M", {})
    rh2m_dict = parameter_data.get("RH2M", {})
    ws10m_dict = parameter_data.get("WS10M", {})
    prec_dict = parameter_data.get("PRECTOTCORR", {})

    # Collect all available date keys ('YYYYMMDD')
    date_keys = sorted(set(list(t2m_dict.keys()) + list(rh2m_dict.keys()) +
                           list(ws10m_dict.keys()) + list(prec_dict.keys())))

    observations = []
    for d_str in date_keys:
        try:
            # Parse 'YYYYMMDD' to UTC ISO8601 string 'YYYY-MM-DDT00:00:00Z'
            dt = datetime.strptime(d_str, "%Y%m%d").replace(tzinfo=timezone.utc)
            observed_at = dt.strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            continue

        temp_c = clean_measurement(t2m_dict.get(d_str))
        humid = clean_measurement(rh2m_dict.get(d_str))
        ws_ms = clean_measurement(ws10m_dict.get(d_str))
        prec_mm = clean_measurement(prec_dict.get(d_str))

        # Unit conversion: m/s to km/h (1 m/s = 3.6 km/h)
        wind_kmh = round(ws_ms * 3.6, 2) if ws_ms is not None else None
        if prec_mm is not None:
            prec_mm = round(prec_mm, 2)

        obs = {
            "location_id": location_id,
            "location_name": location_name,
            "latitude": latitude,
            "longitude": longitude,
            "temperature_c": temp_c,
            "humidity_pct": humid,
            "wind_speed_kmh": wind_kmh,
            "rainfall_mm": prec_mm,
            "observed_at": observed_at,
            "data_source": "NASA_POWER_DAILY",
            "source_metadata": source_metadata,
            "is_simulated": False,
            "note": "NASA POWER daily gridded data; the underlying product depends on the parameter and community.",
        }
        observations.append(obs)

    return observations


def create_nasa_power_provider(
    locations: Optional[List[Dict[str, Any]]] = None,
    start_date: str = "20240101",
    end_date: str = "20240101",
    raw_output_dir: Optional[Path] = None,
    processed_output_dir: Optional[Path] = None,
    fetch_func: Callable = fetch_nasa_power_point,
) -> Callable[[], List[Dict[str, Any]]]:
    """
    Factory creating a zero-argument provider callable compatible with get_observations(provider=...).
    
    Optionally persists raw and normalized output files to disk.
    """
    locs = locations or DEFAULT_LOCATIONS

    def provider() -> List[Dict[str, Any]]:
        all_observations = []
        raw_combined = {
            "metadata": {
                "source": "NASA_POWER_DAILY",
                "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "date_range": {"start": start_date, "end": end_date},
                "parameters": TARGET_PARAMETERS,
                "aggregation": "daily",
            },
            "responses": {},
        }

        for loc in locs:
            lid = loc["location_id"]
            lname = loc["location_name"]
            lat = loc["latitude"]
            lon = loc["longitude"]

            raw_resp = fetch_func(
                latitude=lat,
                longitude=lon,
                start_date=start_date,
                end_date=end_date,
            )
            raw_combined["responses"][lid] = raw_resp
            loc_obs = normalize_nasa_power_records(raw_resp, lid, lname, lat, lon)
            all_observations.extend(loc_obs)

        # Optional persistence
        if raw_output_dir:
            raw_output_dir.mkdir(parents=True, exist_ok=True)
            raw_file = raw_output_dir / f"nasa_power_raw_{start_date}_{end_date}.json"
            raw_file.write_text(json.dumps(raw_combined, indent=2), encoding="utf-8")

        if processed_output_dir:
            processed_output_dir.mkdir(parents=True, exist_ok=True)
            proc_file = processed_output_dir / f"nasa_power_observations_{start_date}_{end_date}.json"
            proc_data = {
                "metadata": {
                    "source": "NASA_POWER_DAILY",
                    "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "start_date": start_date,
                    "end_date": end_date,
                    "record_count": len(all_observations),
                    "is_simulated": False,
                },
                "observations": all_observations,
            }
            proc_file.write_text(json.dumps(proc_data, indent=2), encoding="utf-8")

        return all_observations

    return provider
