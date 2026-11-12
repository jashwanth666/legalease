"""Page 1: LegalEase SaaS Executive Dashboard."""

import pandas as pd
import streamlit as st

from frontend.components.risk_cards import render_kpi_card
from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.utils.api_client import APIError


render_page_header(
    "LegalEase Dashboard",
    "Overview of uploaded contracts, automated risk screening findings, and recent analysis reports.",
)

client = get_api_client()
health, docs, selected_id = render_sidebar_context(client)

top_left, top_right = st.columns([3, 1])
with top_left:
    st.subheader("Portfolio Screening Overview")
with top_right:
    if st.button("+ Upload New Contract", type="primary", use_container_width=True):
        st.switch_page("pages/2_Upload_Contract.py")

if health is None:
    st.stop()

total_docs = len(docs)
analyzed_docs = [d for d in docs if d.get("processing_status") == "analyzed"]

high_risk_findings = 0
medium_risk_findings = 0
critical_risk_findings = 0
for d in analyzed_docs:
    try:
        analysis = client.get_analysis(d["document_id"])
        dist = analysis.get("risk_distribution", {})
        critical_risk_findings += int(dist.get("critical", 0))
        high_risk_findings += int(dist.get("high", 0))
        medium_risk_findings += int(dist.get("medium", 0))
    except APIError:
        pass

c1, c2, c3, c4 = st.columns(4)
with c1:
    render_kpi_card("Total Uploaded Documents", total_docs, "Stored securely in LegalEase", "#0F2744")
with c2:
    render_kpi_card("Total Analyzed Contracts", len(analyzed_docs), "Completed LangGraph workflows", "#1D4ED8")
with c3:
    render_kpi_card(
        "High & Critical Findings",
        high_risk_findings + critical_risk_findings,
        f"{critical_risk_findings} critical • {high_risk_findings} high",
        "#EA580C",
    )
with c4:
    render_kpi_card("Medium-Risk Findings", medium_risk_findings, "Clauses needing review", "#CA8A04")

st.divider()

left_col, right_col = st.columns([3, 2])

with left_col:
    st.subheader("Recent Documents")
    if docs:
        table_rows = [
            {
                "Document ID": d["document_id"],
                "Filename": d["filename"],
                "Type": d["file_type"].upper(),
                "Pages": d.get("page_count", 0),
                "Status": d["processing_status"],
                "Risk Score": (
                    f"{d['overall_risk_score']}/100 ({(d.get('overall_risk_level') or '').upper()})"
                    if d.get("overall_risk_score") is not None
                    else "—"
                ),
            }
            for d in docs[:10]
        ]
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

        action_col1, action_col2, action_col3 = st.columns(3)
        with action_col1:
            if selected_id and st.button("Open Document Analysis", use_container_width=True):
                st.switch_page("pages/Document_Analysis.py")
        with action_col2:
            if selected_id and st.button("Open Risk Assessment", use_container_width=True):
                st.switch_page("pages/3_Risk_Analysis.py")
        with action_col3:
            if selected_id and st.button("Delete Active Document", use_container_width=True):
                try:
                    client.delete_document(selected_id)
                    st.session_state["selected_document_id"] = None
                    st.success(f"Deleted {selected_id}.")
                    st.rerun()
                except APIError as exc:
                    st.error(exc.message)
    else:
        st.info("No contracts uploaded yet. Click **+ Upload New Contract** to get started.")

with right_col:
    st.subheader("Recent Analysis Reports")
    try:
        reports = client.list_reports()
    except APIError:
        reports = []

    if reports:
        for rep in reports[:6]:
            score = rep.get("overall_risk_score")
            lvl = (rep.get("overall_risk_level") or "low").upper()
            st.markdown(
                f"""
                <div class="le-card">
                    <strong>{rep['filename']}</strong> ({rep['document_id']})<br/>
                    <span style="font-size:0.84rem; color:#475569;">
                        Type: {rep.get('detected_contract_type') or 'General'} &bull;
                        Score: {score if score is not None else '—'}/100 ({lvl})
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if st.button("Go to Reports Center", use_container_width=True):
            st.switch_page("pages/5_Reports.py")
    else:
        st.info("Generated PDF analysis reports will appear here after analyzing a contract.")

render_disclaimer_footer()

