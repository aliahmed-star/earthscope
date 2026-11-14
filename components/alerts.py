# components/alerts.py
import streamlit as st
import pandas as pd


def render_alerts(df_incidents: pd.DataFrame):
    """
    Render active alerts navigation component.
    Returns the currently selected incident row (as a dict/Series) or None.
    """
    st.subheader("Active Incidents & Alerts")

    if df_incidents is None or df_incidents.empty:
        st.info("No active incidents found.")
        return None

    if "alert_index" not in st.session_state:
        st.session_state.alert_index = 0

    total = len(df_incidents)
    idx = st.session_state.alert_index % total
    current_inc = df_incidents.iloc[idx]

    col1, col2, col3 = st.columns([1, 4, 1])
    with col1:
        if st.button("◀ Prev"):
            st.session_state.alert_index = (st.session_state.alert_index - 1) % total
            st.rerun()

    inc_id = current_inc.get("incident_id", current_inc.get("id", "N/A"))
    loc_name = current_inc.get("location_name", current_inc.get("location", "Unknown"))
    hazard = current_inc.get("hazard_type", "Unknown")
    risk = current_inc.get("risk_level", "Unknown")
    status = current_inc.get("status", "Pending")

    with col2:
        st.markdown(
            f"**[{inc_id}] {loc_name}**  \n"
            f"**Hazard:** {hazard} &nbsp;|&nbsp; **Risk:** `{risk}` &nbsp;|&nbsp; **Status:** `{status}`"
        )

    with col3:
        if st.button("Next ▶"):
            st.session_state.alert_index = (st.session_state.alert_index + 1) % total
            st.rerun()

    return current_inc
