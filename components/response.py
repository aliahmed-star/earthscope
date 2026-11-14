# components/response.py
import streamlit as st
from earthscope.incidents import IncidentError, IncidentStore


def render_response_panel(current_inc, store: IncidentStore):
    """
    Render incident response controls and details connected to the real IncidentStore.
    """
    st.markdown("### Incident Details & Response Workflow")

    inc_id = current_inc.get("incident_id", current_inc.get("id"))
    if not inc_id:
        st.warning("No incident ID available.")
        return

    # Fetch latest incident state from store
    try:
        live_inc = store.get_incident(inc_id)
    except IncidentError:
        live_inc = current_inc

    status = live_inc.get("status", "Pending")
    risk_level = live_inc.get("risk_level", "Unknown")
    hazard = live_inc.get("hazard_type", "Unknown")

    # Display metadata and explanations
    reasons = live_inc.get("risk_explanation", live_inc.get("reasons", []))
    if isinstance(reasons, list):
        reason_text = "  \n".join(f"• {r}" for r in reasons)
    else:
        reason_text = str(reasons)

    st.markdown(f"**Current Status:** `{status}`")
    st.markdown(f"**Hazard & Risk:** {hazard} ({risk_level})")
    st.markdown(f"**Assessment Explanation:**  \n{reason_text}")

    # Supporting measurements
    supp_meas = live_inc.get("supporting_measurements", {})
    if supp_meas:
        metrics_cols = st.columns(len(supp_meas))
        for col, (k, v) in zip(metrics_cols, supp_meas.items()):
            label = k.replace("_", " ").title()
            col.metric(label, f"{v}")

    st.markdown("#### Actions")
    col1, col2 = st.columns(2)
    with col1:
        if status == "Pending":
            if st.button("Start Response", key=f"start_{inc_id}"):
                try:
                    store.start_response(inc_id, operator_note="Operator initiated response via dashboard.")
                    st.success("Response started: In Progress")
                    st.rerun()
                except IncidentError as err:
                    st.error(f"Error: {err.message}")
        else:
            st.button("Start Response", key=f"start_{inc_id}", disabled=True)

    with col2:
        if status == "In Progress":
            if st.button("Resolve Incident", key=f"resolve_{inc_id}"):
                try:
                    store.resolve_incident(inc_id, operator_note="Operator resolved incident via dashboard.")
                    st.success("Incident resolved: Resolved")
                    st.rerun()
                except IncidentError as err:
                    st.error(f"Error: {err.message}")
        else:
            st.button("Resolve Incident", key=f"resolve_{inc_id}", disabled=True)
