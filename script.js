/* Legacy incident-table helper. The primary dashboard uses the inline client in index.html. */
const API_URL = window.EARTHSCOPE_API_URL || (location.protocol === 'file:' ? 'http://127.0.0.1:8000' : location.origin);
const RISK_COLORS = {Low: '#34d399', Moderate: '#fbbf24', High: '#fb923c', Critical: '#f43f5e'};

async function fetchData() {
    const statusIndicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    const totalIncidentsEl = document.getElementById('total-incidents');
    const tableBody = document.getElementById('incidents-table-body');
    if (!statusIndicator || !statusText || !totalIncidentsEl || !tableBody) return;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
        const statusRes = await fetch(`${API_URL}/api/status`, {signal: controller.signal});
        if (!statusRes.ok) throw new Error(`Backend returned HTTP ${statusRes.status}`);
        statusIndicator.className = 'online';
        statusText.textContent = 'Backend Online';

        const incidentsRes = await fetch(`${API_URL}/api/incidents`, {signal: controller.signal});
        if (!incidentsRes.ok) throw new Error(`Incident request returned HTTP ${incidentsRes.status}`);
        const payload = await incidentsRes.json();
        const incidents = Array.isArray(payload?.incidents) ? payload.incidents : [];

        totalIncidentsEl.textContent = String(incidents.length);
        tableBody.replaceChildren();
        for (const incident of incidents) {
            const row = document.createElement('tr');
            const fields = [
                incident.incident_id,
                incident.hazard_type,
                incident.location_name,
                incident.risk_level,
            ];
            fields.forEach((value, index) => {
                const cell = document.createElement('td');
                cell.textContent = value == null ? '–' : String(value);
                if (index === 3) {
                    cell.style.color = RISK_COLORS[incident.risk_level] || '#94a3b8';
                    cell.style.fontWeight = 'bold';
                }
                row.appendChild(cell);
            });
            tableBody.appendChild(row);
        }
    } catch (error) {
        statusIndicator.className = 'offline';
        statusText.textContent = 'Backend Offline';
        console.error('Connection error:', error);
    } finally {
        clearTimeout(timeout);
    }
}

window.addEventListener('DOMContentLoaded', fetchData);
