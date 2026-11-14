"""Optional legacy Streamlit incident view for the FastAPI backend."""
import os

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.environ.get("EARTHSCOPE_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="GEOSTORM / EarthScope", page_icon="🌍", layout="wide")


@st.cache_data(ttl=5)
def fetch_api_status():
    try:
        response = requests.get(f"{API_BASE_URL}/api/status", timeout=3)
        response.raise_for_status()
        return True, response.json()
    except requests.RequestException as exc:
        return False, {"error": str(exc)}
    except ValueError as exc:
        return False, {"error": f"Backend returned invalid JSON: {exc}"}


@st.cache_data(ttl=10)
def fetch_live_incidents():
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/incidents",
            params={"mode": "live"},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        incidents = payload.get("incidents") if isinstance(payload, dict) else None
        if not isinstance(incidents, list):
            return [], "Backend response did not contain an incidents list."
        return incidents, None
    except requests.RequestException as exc:
        return [], str(exc)
    except ValueError as exc:
        return [], f"Backend returned invalid JSON: {exc}"


st.sidebar.title("System status")
is_online, status_data = fetch_api_status()
if is_online:
    st.sidebar.success("FastAPI backend is online")
    with st.sidebar.expander("Backend status details"):
        st.sidebar.json(status_data)
else:
    st.sidebar.error("FastAPI backend is offline")
    st.sidebar.caption(status_data.get("error", "Unknown connection error"))

if st.sidebar.button("Refresh backend data"):
    st.cache_data.clear()
    st.rerun()

st.title("GEOSTORM / EarthScope")
st.caption("Prototype incident workflow for NASA POWER environmental data. Risk thresholds are for demonstration only.")

if not is_online:
    st.warning("No backend data is available. Start the FastAPI service and refresh this page.")
    st.code("python -m uvicorn api:app --host 127.0.0.1 --port 8000", language="bash")
else:
    incidents, error = fetch_live_incidents()
    if error:
        st.error(f"Could not load incident data: {error}")
    else:
        col1, col2 = st.columns(2)
        col1.metric("NASA POWER-mode incidents", len(incidents))
        col2.metric("Active incidents", sum(item.get("status") != "Resolved" for item in incidents))
        st.subheader("Live-mode incident register")
        if incidents:
            st.dataframe(incidents, use_container_width=True)
            locations = [
                {"lat": item.get("latitude"), "lon": item.get("longitude")}
                for item in incidents
                if item.get("latitude") is not None and item.get("longitude") is not None
            ]
            if locations:
                st.subheader("Incident locations")
                st.map(pd.DataFrame(locations), use_container_width=True)
        else:
            st.info("No incident has been registered from the current NASA POWER-mode assessments.")
