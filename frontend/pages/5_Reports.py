"""Page 7: Executive PDF Audit Reports & Export Hub."""

import html
import streamlit as st

from frontend.components.risk_cards import RISK_COLORS, clean_html, render_kpi_card, risk_badge_html
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
    title="Executive Reports",
    subtitle="Download audit-ready, publication-grade PDF contract summaries, risk scoring tables, and comparative benchmarks.",
    category="Audit Reports",
    active_doc_name=selected_id,
)

if health is None:
    st.error("Backend offline. Please start or connect to the LegalEase API server.")
    st.stop()

# Active Contract Report Hero Section
if selected_id:
    st.markdown(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">Active Contract Audit Dossier</h3>
                <p class="le-section-subtitle">Download executive PDF review for the currently selected agreement</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    try:
        analysis = client.get_analysis(selected_id)
        score_val = analysis.get("overall_risk_score")
        level_val = str(analysis.get("overall_risk_level", "low")).lower()
        mode_val = analysis.get("analysis_mode", "deterministic_fallback")
        report_ready = analysis.get("report_available", False)

        r_badge = risk_badge_html(level_val)

        st.markdown(
            clean_html(
                f"""
                <div class="le-card" style="border-top:3px solid #356AE6; background:#FFFFFF; margin-bottom:1rem;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem; margin-bottom:0.75rem;">
                        <div>
                            <span style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:#748094;">Contract Audit Summary</span>
                            <div style="font-size:1.2rem; font-weight:800; color:#101B35;">{html.escape(analysis['filename'])}</div>
                        </div>
                        <div style="display:flex; align-items:center; gap:0.6rem;">
                            {r_badge}
                            <span style="font-size:0.85rem; font-weight:700; color:#101B35; background:#F8FAFC; border:1px solid #E6EAF0; padding:0.25rem 0.65rem; border-radius:6px;">
                                Score: {score_val}/100
                            </span>
                        </div>
                    </div>
                    <div style="font-size:0.82rem; color:#748094;">
                        ID: <code>{html.escape(selected_id)}</code> &bull;
                        Type: <strong>{html.escape(analysis.get('detected_contract_type', 'General'))}</strong> &bull;
                        Engine: <code>{html.escape(mode_val)}</code>
                    </div>
                </div>
                """
            ),
            unsafe_allow_html=True,
        )

        if not report_ready:
            st.warning("⚠️ PDF generation has not run or was skipped because the analysis pipeline has not yet completed.")
        else:
            pdf_bytes = client.download_report_bytes(selected_id)
            st.download_button(
                label=f"📥 Download Formal PDF Report (LegalEase_Report_{selected_id}.pdf)",
                data=pdf_bytes,
                file_name=f"LegalEase_Report_{selected_id}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )

    except APIError as exc:
        st.info(f"Report dossier unavailable for active contract: {exc.message}")

st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

# Catalog of All Generated Reports
st.markdown(
    """
    <div class="le-section-header">
        <div>
            <h3 class="le-section-title">All Generated PDF Audit Reports</h3>
            <p class="le-section-subtitle">Catalog of available document summaries across all analyzed agreements</p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    reports = client.list_reports()
except APIError as exc:
    st.error(exc.message)
    reports = []

if not reports:
    st.markdown(
        """
        <div class="le-card" style="text-align:center; padding:2.5rem;">
            <div style="font-size:2rem; margin-bottom:0.5rem;">📑</div>
            <div style="font-size:1.1rem; font-weight:700; color:#101B35;">No Reports Generated Yet</div>
            <div style="font-size:0.84rem; color:#748094; max-width:400px; margin:0.25rem auto 1rem auto;">
                Full PDF reports are automatically compiled with ReportLab whenever a contract completes analysis.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    for idx, rep in enumerate(reports):
        doc_id = rep["document_id"]
        fname = rep.get("filename", doc_id)
        ctype = rep.get("detected_contract_type") or "General Agreement"
        created_at = rep.get("created_at") or "Recently"
        score = rep.get("overall_risk_score")
        level = str(rep.get("overall_risk_level") or "low").lower()
        badge = risk_badge_html(level)

        st.markdown(
            f"""
            <div class="le-card" style="margin-bottom:0.85rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
                    <div>
                        <div style="display:flex; align-items:center; gap:0.5rem;">
                            <span style="font-size:1.1rem;">📄</span>
                            <span style="font-size:1.02rem; font-weight:700; color:#101B35;">{html.escape(fname)}</span>
                            <code style="font-size:0.75rem;">{html.escape(doc_id)}</code>
                        </div>
                        <div style="font-size:0.8rem; color:#748094; margin-top:0.2rem; margin-left:1.6rem;">
                            Type: <strong>{html.escape(ctype)}</strong> &bull; Generated: {html.escape(created_at)}
                        </div>
                    </div>
                    <div style="display:flex; align-items:center; gap:0.75rem;">
                        {badge}
                        <span style="font-size:0.85rem; font-weight:700; color:#101B35;">
                            {score if score is not None else '—'}/100
                        </span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        dl_col1, dl_col2 = st.columns([4, 1])
        with dl_col2:
            try:
                rep_data = client.download_report_bytes(doc_id)
                st.download_button(
                    label="📥 Download PDF",
                    data=rep_data,
                    file_name=f"LegalEase_Report_{doc_id}.pdf",
                    mime="application/pdf",
                    key=f"dl_rep_{doc_id}_{idx}",
                    use_container_width=True,
                )
            except APIError:
                st.caption("Download unavailable")

render_disclaimer_footer()
