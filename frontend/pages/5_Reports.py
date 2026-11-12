"""Page 7: Downloadable PDF Analysis Reports."""

import streamlit as st

from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.utils.api_client import APIError


render_page_header(
    "Reports",
    "Download structured ReportLab PDF reports containing executive summaries, risk scores, template comparisons, and disclaimers.",
)

client = get_api_client()
health, _, selected_id = render_sidebar_context(client)

if health is None:
    st.stop()

if selected_id:
    st.subheader(f"Active Contract Report ({selected_id})")
    try:
        analysis = client.get_analysis(selected_id)
        c1, c2, c3 = st.columns(3)
        c1.metric("Contract", analysis["filename"])
        c2.metric(
            "Overall Risk",
            f"{analysis['overall_risk_score']}/100 ({analysis['overall_risk_level'].replace('_', ' ').upper()})",
        )
        c3.metric("Analysis Mode", analysis.get("analysis_mode", "deterministic_fallback"))
        if analysis.get("fallback_used"):
            st.warning(
                f"Report reflects `{analysis.get('analysis_mode')}` results "
                f"(Gemini status: `{analysis.get('gemini_status')}` — {analysis.get('fallback_reason')})."
            )

        if not analysis.get("report_available"):
            st.warning("PDF report is not available until the complete analysis workflow succeeds.")
        else:
            pdf_bytes = client.download_report_bytes(selected_id)
            st.download_button(
                label=f"Download PDF Report (LegalEase_Report_{selected_id}.pdf)",
                data=pdf_bytes,
                file_name=f"LegalEase_Report_{selected_id}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
    except APIError as exc:
        st.info(f"Report unavailable for active contract: {exc.message}")

st.divider()
st.subheader("All Generated Reports")
try:
    reports = client.list_reports()
except APIError as exc:
    st.error(exc.message)
    reports = []

if not reports:
    st.info("No PDF reports have been generated yet.")
else:
    for idx, rep in enumerate(reports):
        doc_id = rep["document_id"]
        col1, col2, col3 = st.columns([3, 2, 2])
        with col1:
            st.markdown(f"**{rep['filename']}** (`{doc_id}`)")
            st.caption(f"Type: {rep.get('detected_contract_type') or 'General'} • Created: {rep.get('created_at')}")
        with col2:
            score = rep.get("overall_risk_score")
            lvl = (rep.get("overall_risk_level") or "low").upper()
            st.markdown(f"Risk: **{score if score is not None else '—'}/100 ({lvl})**")
        with col3:
            try:
                data = client.download_report_bytes(doc_id)
                st.download_button(
                    label="Download PDF",
                    data=data,
                    file_name=f"LegalEase_Report_{doc_id}.pdf",
                    mime="application/pdf",
                    key=f"dl_rep_{doc_id}_{idx}",
                    use_container_width=True,
                )
            except APIError:
                st.caption("Unavailable")

render_disclaimer_footer()

