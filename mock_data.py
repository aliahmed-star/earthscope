from datetime import datetime, timedelta
import math

import pandas as pd

_NOW = datetime(2026, 11, 13, 12, 0)

# ---------- الجزء 1: الحوادث ----------
_INCIDENTS = [
    dict(id="INC-001", location="Cairo", country="Egypt", lat=30.04, lon=31.24,
         hazard_type="Heatwave", risk_level="Critical",
         reasons="Temp above 44C for 3 days, low humidity", status="Pending",
         detected_at=_NOW - timedelta(days=1, hours=6)),
    dict(id="INC-002", location="Alexandria", country="Egypt", lat=31.20, lon=29.92,
         hazard_type="Storm surge", risk_level="Moderate",
         reasons="Wind 62 km/h, heavy rainfall", status="Pending",
         detected_at=_NOW - timedelta(hours=9)),
    dict(id="INC-003", location="Tokyo", country="Japan", lat=35.68, lon=139.69,
         hazard_type="Typhoon", risk_level="High",
         reasons="Wind 110 km/h, rainfall 80 mm", status="Pending",
         detected_at=_NOW - timedelta(days=2)),
    dict(id="INC-004", location="Manila", country="Philippines", lat=14.60, lon=120.98,
         hazard_type="Flood", risk_level="High",
         reasons="Rainfall 140 mm in 24h", status="Pending",
         detected_at=_NOW - timedelta(days=1)),
    dict(id="INC-005", location="Santiago", country="Chile", lat=-33.45, lon=-70.67,
         hazard_type="Wildfire risk", risk_level="Low",
         reasons="Dry vegetation, mild wind", status="Pending",
         detected_at=_NOW - timedelta(hours=20)),
]


# ---------- الجزء 2: دوال الـ data contract ----------
def get_incidents() -> pd.DataFrame:
    return pd.DataFrame(_INCIDENTS)


def start_response(incident_id: str) -> str:
    return "In Progress"


def resolve_incident(incident_id: str) -> str:
    return "Resolved"


# ---------- الجزء 3: القياسات (للـ Trends) ----------
def load_observations() -> pd.DataFrame:
    rows = []
    for inc in _INCIDENTS:
        base = 34 if inc["hazard_type"] == "Heatwave" else 24
        for h in range(0, 96, 4):  # 4 أيام، قياس كل 4 ساعات
            rows.append(dict(
                location=inc["location"], lat=inc["lat"], lon=inc["lon"],
                temperature_c=round(base + 6 * math.sin(h / 24 * 2 * math.pi) + h * 0.05, 1),
                humidity_pct=round(55 - 10 * math.sin(h / 12), 1),
                wind_kmh=round(20 + 8 * math.cos(h / 10), 1),
                rainfall_mm=round(max(0, 4 * math.sin(h / 7)), 1),
                timestamp=_NOW - timedelta(hours=96 - h),
            ))
    return pd.DataFrame(rows)