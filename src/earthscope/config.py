"""
config.py - central configuration for the GEOSTORM / earthscope system logic.

RESPONSIBILITY
    Holds every adjustable value in one place so that no other module has
    "magic numbers" hidden inside its functions:
      * risk-level names and their ordering
      * valid measurement ranges (used by data_loader.py to reject bad data)
      * hazard rules and thresholds (used by analysis.py to detect hazards)
      * incident response states and allowed transitions (used by incidents.py)
      * file locations and a few application defaults

HOW OTHER MODULES USE IT
    data_loader.py -> MEASUREMENT_FIELDS, VALID_RANGES, DEMO_DATA_PATH
    analysis.py    -> RISK_LEVELS, RISK_RANK, ALERT_MIN_LEVEL, HAZARD_RULES, labels
    incidents.py   -> RESPONSE_STATUSES, ALLOWED_TRANSITIONS, INCIDENT_STORE_PATH

IMPORTANT DISCLAIMER
    All thresholds below are PROTOTYPE values chosen to make a believable
    classroom demonstration. They are NOT official meteorological warning
    standards and are NOT scientifically validated disaster predictions.
    This software never controls real weather, equipment or emergency services.

SECRETS
    No API keys or credentials belong in this file. If a live weather provider
    that needs a key is added later, read it from an environment variable
    (for example os.environ.get("WEATHER_API_KEY")) and never commit it.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. File locations
# ---------------------------------------------------------------------------
# This file lives at <repo>/src/earthscope/config.py, so parents[2] is <repo>.
BASE_DIR = Path(__file__).resolve().parents[2]

# Portable defaults; local installations may move state through environment
# variables without editing application code.
HISTORY_DB_PATH = Path(
    os.environ.get("EARTHSCOPE_HISTORY_DB", BASE_DIR / "data" / "historical" / "earthscope_power.sqlite3")
).expanduser()
MODEL_DIR = Path(os.environ.get("EARTHSCOPE_MODEL_DIR", BASE_DIR / "models")).expanduser()

# Offline demonstration dataset (works with no internet connection).
DEMO_DATA_PATH = BASE_DIR / "data" / "processed" / "demo_observations.json"

# Optional JSON file used to keep incidents between application restarts.
INCIDENT_STORE_PATH = BASE_DIR / "data" / "processed" / "incidents.json"

# Persistence is OFF by default: incidents live in memory for the running
# process, which is the simplest reliable option for a demo. Set to True to
# also save them to INCIDENT_STORE_PATH (do not commit that file to git).
PERSIST_INCIDENTS = False

# ---------------------------------------------------------------------------
# 2. Risk levels
# ---------------------------------------------------------------------------
# Ordered from least to most severe. The position in this tuple is the
# "rank" used everywhere to compare levels.
RISK_LEVELS = ("Low", "Moderate", "High", "Critical")
RISK_RANK = {name: rank for rank, name in enumerate(RISK_LEVELS)}

# Assessments at or above this level count as an "alert" (and may become an
# incident). "Low" means nothing noteworthy was detected.
ALERT_MIN_LEVEL = "Moderate"

# ---------------------------------------------------------------------------
# 3. Measurements and valid ranges
# ---------------------------------------------------------------------------
# Canonical field names and units shared by the frontend and system logic.
MEASUREMENT_FIELDS = (
    "temperature_c",    # degrees Celsius
    "humidity_pct",     # relative humidity, percent
    "wind_speed_kmh",   # kilometres per hour
    "rainfall_mm",      # daily precipitation amount (mm/day for NASA POWER)
)

# Human-friendly name and unit for each measurement (used in explanations).
MEASUREMENT_LABELS = {
    "temperature_c": ("Temperature", "°C"),
    "humidity_pct": ("Humidity", "%"),
    "wind_speed_kmh": ("Wind speed", "km/h"),
    "rainfall_mm": ("Rainfall (daily)", "mm/day"),
}

# Physically plausible (min, max) values, inclusive. Anything outside is
# treated as a data error and rejected - never silently clamped or zeroed.
VALID_RANGES = {
    "temperature_c": (-90.0, 60.0),
    "humidity_pct": (0.0, 100.0),
    "wind_speed_kmh": (0.0, 500.0),
    "rainfall_mm": (0.0, 2000.0),
}

# ---------------------------------------------------------------------------
# 4. Hazard names and rules (PROTOTYPE THRESHOLDS)
# ---------------------------------------------------------------------------
HAZARD_HEAT = "Extreme Heat"
HAZARD_COLD = "Extreme Cold"
HAZARD_WIND = "Severe Wind"
HAZARD_RAIN = "Heavy Rainfall"
HAZARD_WILDFIRE = "Wildfire Conditions"
HAZARD_NONE = "None"  # reported when no rule is triggered

# Each rule describes ONE hazard. For every risk level above "Low" it lists
# conditions of the form (measurement_field, operator, threshold).
#   * Operators: ">=" (at or above) and "<=" (at or below). Boundaries are
#     inclusive, so a value exactly equal to the threshold DOES trigger.
#   * A level is reached only when ALL of its conditions are true.
#   * The highest level whose conditions all pass is the hazard's level.
#   * If a needed measurement is missing, that level cannot be confirmed and
#     analysis.py reports it as a limitation instead of guessing.
# The ORDER of this list also breaks ties when two hazards have the same
# level (the earlier rule becomes the "primary" hazard), keeping results
# deterministic.
HAZARD_RULES = [
    {
        "hazard": HAZARD_HEAT,
        "levels": {
            "Moderate": [("temperature_c", ">=", 35.0)],
            "High": [("temperature_c", ">=", 40.0)],
            "Critical": [("temperature_c", ">=", 45.0)],
        },
    },
    {
        "hazard": HAZARD_COLD,
        "levels": {
            "Moderate": [("temperature_c", "<=", -10.0)],
            "High": [("temperature_c", "<=", -20.0)],
            "Critical": [("temperature_c", "<=", -30.0)],
        },
    },
    {
        "hazard": HAZARD_WIND,
        "levels": {
            "Moderate": [("wind_speed_kmh", ">=", 50.0)],
            "High": [("wind_speed_kmh", ">=", 90.0)],
            "Critical": [("wind_speed_kmh", ">=", 120.0)],
        },
    },
    {
        "hazard": HAZARD_RAIN,
        "levels": {
            "Moderate": [("rainfall_mm", ">=", 50.0)],
            "High": [("rainfall_mm", ">=", 100.0)],
            "Critical": [("rainfall_mm", ">=", 150.0)],
        },
    },
    {
        # Combined rule: hot + dry + windy air favours fast-spreading fires.
        "hazard": HAZARD_WILDFIRE,
        "levels": {
            "Moderate": [
                ("temperature_c", ">=", 30.0),
                ("humidity_pct", "<=", 30.0),
                ("wind_speed_kmh", ">=", 30.0),
            ],
            "High": [
                ("temperature_c", ">=", 35.0),
                ("humidity_pct", "<=", 20.0),
                ("wind_speed_kmh", ">=", 40.0),
            ],
            "Critical": [
                ("temperature_c", ">=", 40.0),
                ("humidity_pct", "<=", 15.0),
                ("wind_speed_kmh", ">=", 50.0),
            ],
        },
    },
]

THRESHOLD_SET_NAME = "prototype-v1"
PROTOTYPE_DISCLAIMER = (
    "Prototype rule-based thresholds for demonstration only; not official "
    "meteorological warnings and not a validated disaster prediction."
)

# ---------------------------------------------------------------------------
# 5. Incident response workflow
# ---------------------------------------------------------------------------
STATUS_PENDING = "Pending"
STATUS_IN_PROGRESS = "In Progress"
STATUS_RESOLVED = "Resolved"
RESPONSE_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_RESOLVED)

# Which status may follow which. Skipping a step (Pending -> Resolved) and
# reopening a resolved incident are deliberately not allowed.
ALLOWED_TRANSITIONS = {
    STATUS_PENDING: (STATUS_IN_PROGRESS,),
    STATUS_IN_PROGRESS: (STATUS_RESOLVED,),
    STATUS_RESOLVED: (),
}
