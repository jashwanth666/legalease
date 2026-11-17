"""Page 4: Contract Risk Assessment & Evidence Verification Dashboard."""

import html
import pandas as pd
import streamlit as st

from frontend.components.risk_cards import (
    RISK_COLORS,
    render_kpi_card,
    render_risk_finding_card,
    render_risk_score_gauge,
)
from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.utils.api_client import APIError


client = get_api_client()
health, docs, selected_id = render_sidebar_context(client)

render_page_header(
    title="Risk Assessment",
    subtitle="AI legal risk detection, unfavorable clause scoring, and verified evidentiary proof.",
    category="Risk Engine",
    active_doc_name=selected_id,
)

if health is None:
    st.error("Backend offline. Please start or connect to the LegalEase API server.")
    st.stop()

if not selected_id:
    st.markdown(
        """
        <div class="le-card" style="text-align:center; padding:2rem;">
            <div style="font-size:2rem; margin-bottom:0.5rem;">🛡️</div>
            <div style="font-size:1.1rem; font-weight:700; color:#101B35;">No Contract Selected</div>
            <div style="font-size:0.84rem; color:#748094; max-width:400px; margin:0.25rem auto 1rem auto;">
                Please select an active contract from the sidebar to inspect its risk profile.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

try:
    analysis = client.get_analysis(selected_id)
except APIError as exc:
    st.warning(f"Analysis data not yet available for {selected_id}: {exc.message}")
    if st.button("Go to Document Analysis to Run Pipeline", type="primary"):
        st.switch_page("pages/Document_Analysis.py")
    st.stop()

dist = analysis.get("risk_distribution", {})
overall_score = analysis.get("overall_risk_score", 0.0)
overall_level = str(analysis.get("overall_risk_level", "no_notable_risk")).lower()

# Fallback Transparency Alert
if analysis.get("fallback_used"):
    st.markdown(
        f"""
        <div style="background:#FFFBEB; border:1px solid #FDE68A; border-left:4px solid #E69A32; border-radius:8px; padding:0.75rem 1rem; margin-bottom:1.25rem; font-size:0.83rem; color:#92400E;">
            <strong>Deterministic Screening Active:</strong> Analysis executed in <code>{analysis.get('analysis_mode')}</code> mode
            (Gemini status: <code>{analysis.get('gemini_status')}</code> &mdash; {analysis.get('fallback_reason') or 'Heuristic model'}).
            Findings are generated from local deterministic heuristics, not Google Gemini LLM synthesis.
        </div>
        """,
        unsafe_allow_html=True,
    )

# 1. Large Hero Overall Risk Score Visualizer
render_risk_score_gauge(
    score=overall_score,
    level=overall_level,
    limitations=analysis.get("scoring_limitations"),
    mode=analysis.get("analysis_mode"),
)

st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

# 2. Risk Distribution Metric Cards Row
k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    render_kpi_card("Critical", dist.get("critical", 0), "Score 80–100", RISK_COLORS["critical"], icon="🚨")
with k2:
    render_kpi_card("High", dist.get("high", 0), "Score 60–79", RISK_COLORS["high"], icon="⚠️")
with k3:
    render_kpi_card("Medium", dist.get("medium", 0), "Score 30–59", RISK_COLORS["medium"], icon="⚡")
with k4:
    render_kpi_card("Low", dist.get("low", 0), "Score 1–29", RISK_COLORS["low"], icon="✓")
with k5:
    render_kpi_card("Routine / Safe", dist.get("no_notable_risk", 0), "Unscored provisions", RISK_COLORS["no_notable_risk"], icon="🛡️")

st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

# 3. Visual Breakdown Chart
chart_col, info_col = st.columns([3, 2])
with chart_col:
    st.markdown(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">Risk Severity Breakdown</h3>
                <p class="le-section-subtitle">Clause breakdown by severity category in this contract</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    chart_df = pd.DataFrame(
        {
            "Severity Tier": ["Critical", "High", "Medium", "Low", "Uncertain", "Routine"],
            "Clause Count": [
                dist.get("critical", 0),
                dist.get("high", 0),
                dist.get("medium", 0),
                dist.get("low", 0),
                dist.get("uncertain", 0),
                dist.get("no_notable_risk", 0),
            ],
        }
    ).set_index("Severity Tier")
    st.bar_chart(chart_df, color="#356AE6", height=220)

with info_col:
    st.markdown(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">Review Recommendations</h3>
                <p class="le-section-subtitle">Priority review steps for counsel</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    crit = int(dist.get("critical", 0))
    hi = int(dist.get("high", 0))
    if crit > 0:
        badge_text = f"Action Required: {crit} Critical Risk Clauses"
        badge_color = "#DC4545"
        desc = "High-liability provisions detected (e.g. strict liability caps, unlimited indemnities, or unilateral waivers). Prompt renegotiation is strongly recommended."
    elif hi > 0:
        badge_text = f"Attention: {hi} High-Risk Terms"
        badge_color = "#E87536"
        desc = "Terms with unfavorable exposure found. Request standard bilateral exceptions before signing."
    else:
        badge_text = "Standard Risk Profile"
        badge_color = "#16A36A"
        desc = "No critical risk deviations detected. Proceed with standard operational clause review."

    st.markdown(
        f"""
        <div class="le-card" style="border-left:4px solid {badge_color};">
            <div style="font-size:0.85rem; font-weight:700; color:{badge_color}; margin-bottom:0.35rem;">
                {badge_text}
            </div>
            <div style="font-size:0.82rem; color:#172033; line-height:1.5;">
                {desc}
            </div>
            <div style="margin-top:0.75rem; font-size:0.75rem; color:#748094;">
                Detected Contract Type: <strong>{analysis.get('detected_contract_type', 'General')}</strong> &bull;
                Embeddings: <code>{analysis.get('embedding_backend')}</code>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

# 4. Individual Risk Findings List with Category Filter
st.markdown(
    """
    <div class="le-section-header">
        <div>
            <h3 class="le-section-title">Itemized Clause Risk Findings</h3>
            <p class="le-section-subtitle">Specific provisions with detected exposures, explanations, impacts, and remediation actions</p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

findings = analysis.get("risk_findings", [])
if not findings:
    st.info("No risk findings identified for this document.")
else:
    available_levels = sorted({str(f.get("risk_level", "no_notable_risk")).lower() for f in findings})
    filter_opts = ["all"] + available_levels

    chosen_tier = st.selectbox(
        "Filter Findings by Severity Level",
        filter_opts,
        format_func=lambda x: "All Severity Levels" if x == "all" else x.replace("_", " ").upper(),
    )

    filtered_findings = [
        f for f in findings
        if chosen_tier == "all" or str(f.get("risk_level", "")).lower() == chosen_tier
    ]

    st.markdown(
        f"""
        <div style="font-size:0.8rem; font-weight:600; color:#748094; margin-bottom:1rem;">
            Showing <strong style="color:#101B35;">{len(filtered_findings)}</strong> of {len(findings)} clause risk assessments
        </div>
        """,
        unsafe_allow_html=True,
    )

    for idx, finding in enumerate(filtered_findings):
        render_risk_finding_card(finding, idx)

render_disclaimer_footer()
