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
overall_level = str(analysis.get("overall_risk_level", "no_notable_risk")).lower()

if analysis.get("fallback_used"):
    st.warning(
        f"Analysis ran in `{analysis.get('analysis_mode')}` mode "
        f"(Gemini status: `{analysis.get('gemini_status')}` — "
        f"{analysis.get('fallback_reason') or 'Fallback screening used'}). "
        "Heuristic pattern results are explicitly marked and not labeled as Gemini AI analysis."
    )

k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    render_kpi_card(
        "Overall Score",
        f"{overall_score}/100",
        overall_level.replace("_", " ").upper(),
        RISK_COLORS.get(overall_level, "#0F2744"),
    )
with k2:
    render_kpi_card("Critical", dist.get("critical", 0), "Score 80–100", RISK_COLORS["critical"])
with k3:
    render_kpi_card("High", dist.get("high", 0), "Score 60–79", RISK_COLORS["high"])
with k4:
    render_kpi_card("Medium", dist.get("medium", 0), "Score 30–59", RISK_COLORS["medium"])
with k5:
    render_kpi_card("Uncertain", dist.get("uncertain", 0), "Manual review", RISK_COLORS["uncertain"])
with k6:
    render_kpi_card(
        "No Flagged Pattern",
        dist.get("no_notable_risk", 0),
        "Unscored routine clauses",
        RISK_COLORS["no_notable_risk"],
    )

st.caption(
    f"Analysis Mode: `{analysis.get('analysis_mode')}` • "
    + (analysis.get("scoring_limitations") or "Scores are prototype screening indicators only.")
)

chart_df = pd.DataFrame(
    {
        "Screening Category": ["Critical", "High", "Medium", "Low", "Uncertain", "No Notable Pattern"],
        "Clause Count": [
            dist.get("critical", 0),
            dist.get("high", 0),
            dist.get("medium", 0),
            dist.get("low", 0),
            dist.get("uncertain", 0),
            dist.get("no_notable_risk", 0),
        ],
    }
).set_index("Screening Category")
st.bar_chart(chart_df)

st.divider()
st.subheader("Clause-by-Clause Risk Findings")

findings = analysis.get("risk_findings", [])
all_levels = ["critical", "high", "medium", "low", "uncertain", "no_notable_risk"]
levels_filter = st.multiselect(
    "Filter by Screening Category",
    all_levels,
    default=all_levels,
)

filtered = [f for f in findings if f.get("risk_level", "no_notable_risk").lower() in levels_filter]
if not filtered:
    st.info("No findings match the selected risk filter.")
else:
    for idx, finding in enumerate(filtered):
        render_risk_finding_card(finding, idx)

render_disclaimer_footer()

