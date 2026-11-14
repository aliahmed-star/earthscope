# components/trends.py
import streamlit as st
import pandas as pd
from earthscope.charts import create_trend_chart


def render_trends(df_obs: pd.DataFrame, location_name: str):
    """
    Render environmental trends and indicator charts for a chosen location.
    """
    st.subheader(f"Environmental Indicators & Trends for {location_name}")

    if df_obs is None or df_obs.empty:
        st.warning("No observation data available.")
        return

    # Check for target location
    loc_data = df_obs[
        (df_obs.get("location_name") == location_name) |
        (df_obs.get("location_id") == location_name) |
        (df_obs.get("location") == location_name)
    ]

    if loc_data.empty:
        st.info(f"No specific observation records matched for {location_name}.")
        return

    # Show rich Plotly subplots
    fig = create_trend_chart(df_obs, location_name)
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True)

    # Display raw observations table
    with st.expander("View Raw Measurement Record"):
        st.dataframe(loc_data)
