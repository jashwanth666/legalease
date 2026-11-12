"""Page 3: Document Analysis (Extracted Text, Executive Summary, and Classified Clauses)."""

import streamlit as st

from frontend.components.clause_viewer import render_clause_viewer
from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.utils.api_client import APIError


render_page_header(
    "Document Analysis",
    "Inspect page-referenced extracted text, plain-English executive summary, and classified legal clauses.",
)

client = get_api_client()
health, _, selected_id = render_sidebar_context(client)

if health is None:
    st.stop()

if not selected_id:
    st.info("Select or upload a contract first from the Upload Contract page.")
    st.stop()

try:
    doc_detail = client.get_document(selected_id)
except APIError as exc:
    st.error(exc.message)
    st.stop()

doc = doc_detail["document"]
extracted = doc_detail.get("extracted") or {}

m1, m2, m3, m4 = st.columns(4)
m1.metric("Document ID", doc["document_id"])
m2.metric("Filename", doc["filename"])
m3.metric("Pages", doc.get("page_count", 0))
m4.metric("Status", doc.get("processing_status", "").upper())

if doc.get("processing_status") != "analyzed":
    if doc.get("ocr_required"):
        st.warning("This PDF appears scanned and requires OCR before analysis.")
    else:
        st.info("This document has not been analyzed yet. Click below to run the LangGraph workflow.")
        if st.button("Analyze Contract Now", type="primary"):
            with st.spinner("Running LegalEase analysis pipeline..."):
                try:
                    client.analyze_document(selected_id)
                    st.success("Analysis completed!")
                    st.rerun()
                except APIError as exc:
                    st.error(exc.message)

tab_summary, tab_clauses, tab_pages = st.tabs(
    ["Executive Summary", "Classified Clauses", "Extracted Page Text"]
)

with tab_summary:
    if doc.get("processing_status") == "analyzed":
        try:
            analysis = client.get_analysis(selected_id)
            st.caption(
                f"Detected Type: **{analysis.get('detected_contract_type')}** • "
                f"Analysis Mode: `{analysis.get('analysis_mode')}`"
            )
            st.markdown(analysis.get("executive_summary", "No summary generated."))
        except APIError as exc:
            st.error(exc.message)
    else:
        st.info("Executive summary becomes available once contract analysis completes.")

with tab_clauses:
    if doc.get("processing_status") == "analyzed":
        try:
            clauses_resp = client.get_clauses(selected_id)
            render_clause_viewer(clauses_resp.get("clauses", []))
        except APIError as exc:
            st.error(exc.message)
    else:
        st.info("Run contract analysis to segment and classify clauses.")

with tab_pages:
    pages = extracted.get("pages", [])
    if not pages:
        st.info("No extracted page data found.")
    else:
        for page in pages:
            pno = page.get("page_number", 1)
            with st.expander(f"Page {pno}", expanded=(pno == 1)):
                if page.get("headings"):
                    st.caption("Detected Headings: " + " | ".join(page["headings"]))
                st.text_area(
                    f"Page {pno} text",
                    value=page.get("text", ""),
                    height=220,
                    disabled=True,
                    key=f"page_txt_{selected_id}_{pno}",
                    label_visibility="collapsed",
                )

render_disclaimer_footer()

