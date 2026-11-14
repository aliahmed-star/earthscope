# components/globe.py
import pydeck as pdk
import streamlit as st
import pandas as pd


# Color mapping for risk levels: [R, G, B, Alpha]
RISK_COLORS = {
    "Critical": [255, 69, 0, 200],     # Bright red-orange
    "High": [255, 140, 0, 180],         # Orange
    "Moderate": [255, 215, 0, 170],     # Gold/yellow
    "Low": [46, 139, 87, 160],          # Sea green
}


def build_globe(df_incidents: pd.DataFrame) -> pdk.Deck:
    """Build a PyDeck 3D visualization layer of monitored incidents on the globe."""
    lat_center, lon_center, zoom = 20, 0, 1.2

    if df_incidents.empty:
        # Render empty or base world view
        view_state = pdk.ViewState(
            latitude=lat_center,
            longitude=lon_center,
            zoom=zoom,
            pitch=0,
        )
        return pdk.Deck(
            layers=[],
            initial_view_state=view_state,
            map_style="mapbox://styles/mapbox/dark-v10"
        )

    # Prepare DataFrame with color and coordinates
    df_plot = df_incidents.copy()

    # Normalize latitude/longitude column names
    if "longitude" not in df_plot.columns and "lon" in df_plot.columns:
        df_plot["longitude"] = df_plot["lon"]
    if "latitude" not in df_plot.columns and "lat" in df_plot.columns:
        df_plot["latitude"] = df_plot["lat"]

    # Assign RGBA color based on risk level
    def get_color(risk):
        return RISK_COLORS.get(risk, [255, 69, 0, 180])

    df_plot["color"] = df_plot["risk_level"].apply(get_color)

    # Determine radius by risk level (Critical larger than Low)
    radius_map = {"Critical": 300000, "High": 220000, "Moderate": 160000, "Low": 100000}
    df_plot["radius"] = df_plot["risk_level"].map(radius_map).fillna(150000)

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_plot,
        get_position=["longitude", "latitude"],
        get_color="color",
        get_radius="radius",
        pickable=True,
        auto_highlight=True,
    )

    view_state = pdk.ViewState(
        latitude=lat_center,
        longitude=lon_center,
        zoom=zoom,
        pitch=0,
    )

    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        tooltip={
            "text": "Location: {location_name}\nHazard: {hazard_type}\nRisk: {risk_level}\nStatus: {status}"
        },
        map_style="mapbox://styles/mapbox/dark-v10"
    )
    return deck
