"""
charts.py - Plotly and visualization utilities for environmental trends and observations.
"""
from typing import List, Dict, Any, Optional
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def create_trend_chart(df_obs: pd.DataFrame, location_name: str) -> Optional[go.Figure]:
    """
    Build a multi-metric environmental trend or measurement overview chart
    for a given location.
    """
    if df_obs.empty:
        return None

    # Filter for the target location (matching location_name or location_id)
    loc_data = df_obs[
        (df_obs.get("location_name") == location_name) |
        (df_obs.get("location_id") == location_name) |
        (df_obs.get("location") == location_name)
    ]
    if loc_data.empty:
        loc_data = df_obs

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("Temperature (°C)", "Humidity (%)", "Wind Speed (km/h)", "Rainfall (mm/day)"),
        vertical_spacing=0.15,
        horizontal_spacing=0.12
    )

    # Pick appropriate timestamp / index for x-axis
    x_axis = loc_data["observed_at"] if "observed_at" in loc_data.columns else (
        loc_data["timestamp"] if "timestamp" in loc_data.columns else loc_data.index
    )

    if "temperature_c" in loc_data.columns:
        fig.add_trace(
            go.Scatter(x=x_axis, y=loc_data["temperature_c"], mode="lines+markers", name="Temp (°C)",
                       line=dict(color="#FF4500", width=2)),
            row=1, col=1
        )
    if "humidity_pct" in loc_data.columns:
        fig.add_trace(
            go.Scatter(x=x_axis, y=loc_data["humidity_pct"], mode="lines+markers", name="Humidity (%)",
                       line=dict(color="#1E90FF", width=2)),
            row=1, col=2
        )
    if "wind_speed_kmh" in loc_data.columns:
        fig.add_trace(
            go.Scatter(x=x_axis, y=loc_data["wind_speed_kmh"], mode="lines+markers", name="Wind (km/h)",
                       line=dict(color="#32CD32", width=2)),
            row=2, col=1
        )
    if "rainfall_mm" in loc_data.columns:
        fig.add_trace(
            go.Bar(x=x_axis, y=loc_data["rainfall_mm"], name="Rain (mm)",
                   marker_color="#4682B4"),
            row=2, col=2
        )

    fig.update_layout(
        title_text=f"Environmental Indicators — {location_name}",
        template="plotly_dark",
        paper_bgcolor="#0A192F",
        plot_bgcolor="#152A45",
        showlegend=False,
        height=400,
        margin=dict(l=40, r=40, t=60, b=40)
    )

    return fig
