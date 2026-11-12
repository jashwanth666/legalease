"""Page 4: Risk Assessment Dashboard."""

import pandas as pd
import streamlit as st

from frontend.components.risk_cards import (
    RISK_COLORS,
    render_kpi_card,
    render_risk_finding_card,
)
from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.utils.api_client import APIError


render_page_header(
    "Risk Assessment",
    "Transparent illustrative risk scoring (40% severity, 30% unfavorable wording, 20% missing protections, 10% ambiguity).",
)

client = get_api_client()
health, _, selected_id = render_sidebar_context(client)

if health is None:
    st.stop()

if not selected_id:
    st.info("Select or upload a contract first.")
    st.stop()

try:
    analysis = client.get_analysis(selected_id)
except APIError as exc:
    st.warning(exc.message)
    st.stop()

dist = analysis.get("risk_distribution", {})
overall_score = analysis.get("overall_risk_score", 0.0)
overall_level = str(analysis.get("overall_risk_level", "low")).lower()

k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    render_kpi_card(
        "Overall Score",
        f"{overall_score}/100",
        f"Level: {overall_level.upper()}",
        RISK_COLORS.get(overall_level, "#0F2744"),
    )
with k2:
    render_kpi_card("Low Risk", dist.get("low", 0), "Score 0–29", RISK_COLORS["low"])
with k3:
    render_kpi_card("Medium Risk", dist.get("medium", 0), "Score 30–59", RISK_COLORS["medium"])
with k4:
    render_kpi_card("High Risk", dist.get("high", 0), "Score 60–79", RISK_COLORS["high"])
with k5:
    render_kpi_card("Critical Risk", dist.get("critical", 0), "Score 80–100", RISK_COLORS["critical"])

st.caption(
    f"Analysis Mode: `{analysis.get('analysis_mode')}` • "
    "Scores are prototype screening indicators, not legally validated standards."
)

chart_df = pd.DataFrame(
    {
        "Risk Level": ["Low", "Medium", "High", "Critical"],
        "Clause Count": [
            dist.get("low", 0),
            dist.get("medium", 0),
            dist.get("high", 0),
            dist.get("critical", 0),
        ],
    }
).set_index("Risk Level")
st.bar_chart(chart_df)

st.divider()
st.subheader("Clause-by-Clause Risk Findings")

findings = analysis.get("risk_findings", [])
levels_filter = st.multiselect(
    "Filter by Risk Level",
    ["critical", "high", "medium", "low"],
    default=["critical", "high", "medium", "low"],
)

filtered = [f for f in findings if f.get("risk_level", "low").lower() in levels_filter]
if not filtered:
    st.info("No findings match the selected risk filter.")
else:
    for idx, finding in enumerate(filtered):
        render_risk_finding_card(finding, idx)

render_disclaimer_footer()

