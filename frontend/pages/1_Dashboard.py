"""Page 1: LegalEase SaaS Executive Intelligence Dashboard."""

import html
import pandas as pd
import streamlit as st

from frontend.components.risk_cards import RISK_COLORS, render_kpi_card, risk_badge_html
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
    title="Executive Dashboard",
    subtitle="Continuous contract intelligence, automated risk screening, and cross-portfolio compliance telemetry.",
    category="Overview",
    active_doc_name=selected_id,
)

if health is None:
    st.error("Cannot connect to LegalEase FastAPI server. Ensure the backend is active at http://127.0.0.1:8000.")
    st.stop()

# Top Hero / Welcome Banner with Primary CTA
welcome_col, cta_col = st.columns([3, 1])
with welcome_col:
    st.markdown(
        """
        <div style="margin-bottom:1rem;">
            <div style="font-size:1.15rem; font-weight:700; color:#101B35;">
                Welcome to LegalEase Enterprise
            </div>
            <div style="font-size:0.86rem; color:#748094; margin-top:0.2rem;">
                AI-powered contract risk intelligence, automated clause extraction, benchmark comparisons, and structured PDF audits.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with cta_col:
    if st.button("➕ Upload New Contract", type="primary", use_container_width=True):
        st.switch_page("pages/2_Upload_Contract.py")

# Compute Real Portfolio Metrics
total_docs = len(docs)
analyzed_docs = [d for d in docs if d.get("processing_status") == "analyzed"]
pending_docs = [d for d in docs if d.get("processing_status") in {"uploaded", "processing", "partially_analyzed"}]

critical_count = 0
high_count = 0
medium_count = 0
low_count = 0
uncertain_count = 0
no_risk_count = 0
risk_scores: list[float] = []

for d in analyzed_docs:
    s = d.get("overall_risk_score")
    if s is not None:
        risk_scores.append(float(s))
    try:
        analysis = client.get_analysis(d["document_id"])
        dist = analysis.get("risk_distribution", {})
        critical_count += int(dist.get("critical", 0))
        high_count += int(dist.get("high", 0))
        medium_count += int(dist.get("medium", 0))
        low_count += int(dist.get("low", 0))
        uncertain_count += int(dist.get("uncertain", 0))
        no_risk_count += int(dist.get("no_notable_risk", 0))
    except APIError:
        pass

avg_risk_score = round(sum(risk_scores) / len(risk_scores), 1) if risk_scores else 0.0

# 4 Hero Metric Cards
k1, k2, k3, k4 = st.columns(4)
with k1:
    render_kpi_card(
        label="Total Analyzed Contracts",
        value=len(analyzed_docs),
        subtitle=f"{total_docs} total in vault",
        accent="#101B35",
        icon="📑",
    )
with k2:
    render_kpi_card(
        label="High & Critical Risks",
        value=high_count + critical_count,
        subtitle=f"{critical_count} critical • {high_count} high",
        accent="#DC4545" if (high_count + critical_count) > 0 else "#16A36A",
        icon="🛡️",
    )
with k3:
    render_kpi_card(
        label="Pending Review",
        value=len(pending_docs),
        subtitle="Unanalyzed or in progress",
        accent="#E69A32",
        icon="⏳",
    )
with k4:
    render_kpi_card(
        label="Portfolio Avg Risk Score",
        value=f"{avg_risk_score}/100" if risk_scores else "N/A",
        subtitle="Across analyzed agreements",
        accent="#356AE6",
        icon="⚖️",
    )

st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

# Main Grid: Risk Distribution Chart + Quick Actions & Recent Activity
grid_left, grid_right = st.columns([3, 2])

with grid_left:
    st.markdown(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">Portfolio Risk Distribution</h3>
                <p class="le-section-subtitle">Aggregate clause counts grouped by severity across all analyzed contracts</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if analyzed_docs:
        dist_df = pd.DataFrame(
            {
                "Severity Level": ["Critical", "High", "Medium", "Low", "Uncertain", "Routine / No Risk"],
                "Count": [critical_count, high_count, medium_count, low_count, uncertain_count, no_risk_count],
            }
        ).set_index("Severity Level")
        st.bar_chart(dist_df, color="#356AE6", height=240)
    else:
        st.info("Upload and analyze a contract to populate the portfolio risk distribution.")

with grid_right:
    st.markdown(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">Quick Action Hub</h3>
                <p class="le-section-subtitle">Jump directly into contract intelligence workflows</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="le-card" style="margin-bottom:0.75rem;">
            <div style="font-size:0.84rem; font-weight:700; color:#101B35; margin-bottom:0.25rem;">
                Contract Ingestion
            </div>
            <div style="font-size:0.78rem; color:#748094;">
                Upload non-disclosure agreements, master service agreements, or vendor contracts.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    qa_col1, qa_col2 = st.columns(2)
    with qa_col1:
        if st.button("📄 Document Analysis", use_container_width=True):
            st.switch_page("pages/Document_Analysis.py")
    with qa_col2:
        if st.button("🛡️ Risk Assessment", use_container_width=True):
            st.switch_page("pages/3_Risk_Analysis.py")

    qa_col3, qa_col4 = st.columns(2)
    with qa_col3:
        if st.button("⚖️ Clause Benchmark", use_container_width=True):
            st.switch_page("pages/4_Clause_Comparison.py")
    with qa_col4:
        if st.button("📑 Reports Center", use_container_width=True):
            st.switch_page("pages/5_Reports.py")

st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

# Recent Documents Table with Enterprise Status Pills & Action Toolbar
st.markdown(
    """
    <div class="le-section-header">
        <div>
            <h3 class="le-section-title">Recent Contracts & Portfolio Ledger</h3>
            <p class="le-section-subtitle">Real-time status, detected types, risk scores, and management actions</p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if docs:
    table_rows = []
    for d in docs[:12]:
        status_val = d.get("processing_status", "uploaded")
        score_val = d.get("overall_risk_score")
        level_val = d.get("overall_risk_level")
        score_disp = f"{score_val}/100 ({level_val.replace('_', ' ').upper()})" if score_val is not None and level_val else "—"

        table_rows.append(
            {
                "Document ID": d["document_id"],
                "Filename": d["filename"],
                "Format": d["file_type"].upper(),
                "Pages / Layout": f"{d.get('page_count', 0)} Pages" if d["file_type"] == "pdf" else "DOCX Paras",
                "Status": status_val.upper(),
                "Mode": d.get("analysis_mode") or "Pending",
                "Risk Score": score_disp,
            }
        )

    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # Document Actions for Currently Selected Contract
    if selected_id:
        act_col1, act_col2, act_col3 = st.columns([1, 1, 1])
        with act_col1:
            if st.button("🔍 Open Active Document Analysis", use_container_width=True):
                st.switch_page("pages/Document_Analysis.py")
        with act_col2:
            if st.button("🛡️ Open Active Risk Assessment", use_container_width=True):
                st.switch_page("pages/3_Risk_Analysis.py")
        with act_col3:
            if st.button("🗑️ Delete Active Document", type="secondary", use_container_width=True):
                try:
                    client.delete_document(selected_id)
                    st.session_state["selected_document_id"] = None
                    st.success(f"Deleted contract {selected_id}.")
                    st.rerun()
                except APIError as exc:
                    st.error(exc.message)
else:
    st.markdown(
        """
        <div class="le-card" style="text-align:center; padding:2.5rem;">
            <div style="font-size:2rem; margin-bottom:0.5rem;">📁</div>
            <div style="font-size:1.1rem; font-weight:700; color:#101B35;">No Contracts In Vault</div>
            <div style="font-size:0.84rem; color:#748094; max-width:400px; margin:0.25rem auto 1rem auto;">
                Get started by uploading your first commercial agreement, or load one of the included demo contracts.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

render_disclaimer_footer()
