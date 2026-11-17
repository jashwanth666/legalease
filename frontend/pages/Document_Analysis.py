"""Page 3: Document Intelligence & Clause Extraction Overview."""

import html
import streamlit as st

from frontend.components.clause_viewer import render_clause_viewer
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
    title="Document Analysis",
    subtitle="Page-anchored clause segmentation, executive legal synthesis, and automated clause classification.",
    category="Intelligence",
    active_doc_name=selected_id,
)

if health is None:
    st.error("Backend offline. Please start or connect to the LegalEase API server.")
    st.stop()

if not selected_id:
    st.markdown(
        """
        <div class="le-card" style="text-align:center; padding:2rem;">
            <div style="font-size:2rem; margin-bottom:0.5rem;">📄</div>
            <div style="font-size:1.1rem; font-weight:700; color:#101B35;">No Contract Selected</div>
            <div style="font-size:0.84rem; color:#748094; max-width:400px; margin:0.25rem auto 1rem auto;">
                Please select a contract from the sidebar or upload a new agreement.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Go to Upload Contract", type="primary"):
        st.switch_page("pages/2_Upload_Contract.py")
    st.stop()

try:
    doc_detail = client.get_document(selected_id)
except APIError as exc:
    st.error(exc.message)
    st.stop()

doc = doc_detail["document"]
extracted = doc_detail.get("extracted") or {}
proc_status = doc.get("processing_status", "uploaded")

# Contract Summary Banner Card
status_badge_color = "#16A36A" if proc_status == "analyzed" else ("#DC4545" if proc_status == "failed" else "#356AE6")

st.markdown(
    f"""
    <div class="le-card" style="border-top:3px solid {status_badge_color};">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem; margin-bottom:0.75rem;">
            <div>
                <span style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:#748094; letter-spacing:0.05em;">
                    Contract Overview
                </span>
                <div style="font-size:1.2rem; font-weight:800; color:#101B35;">
                    {html.escape(doc['filename'])}
                </div>
            </div>
            <div style="display:flex; align-items:center; gap:0.5rem;">
                <span style="background:{status_badge_color}15; color:{status_badge_color}; border:1px solid {status_badge_color}40; padding:0.25rem 0.65rem; border-radius:999px; font-size:0.75rem; font-weight:700; text-transform:uppercase;">
                    {html.escape(proc_status)}
                </span>
            </div>
        </div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:0.75rem; font-size:0.82rem; color:#748094; padding-top:0.5rem; border-top:1px solid #F1F4F9;">
            <div>Contract ID: <strong style="color:#101B35;">{html.escape(doc['document_id'])}</strong></div>
            <div>File Format: <strong style="color:#101B35;">{html.escape(doc['file_type'].upper())}</strong></div>
            <div>Pagination: <strong style="color:#101B35;">{doc.get('page_count', 0) if doc['file_type'] == 'pdf' else 'DOCX Paras'}</strong></div>
            <div>Analysis Mode: <strong style="color:#101B35;">{html.escape(doc.get('analysis_mode') or 'Pending')}</strong></div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if doc.get("last_error"):
    st.error(f"Last analysis execution error: {doc['last_error']}")

# Analysis Launch / Retry Actions
if proc_status != "analyzed":
    if doc.get("ocr_required"):
        st.warning("⚠️ This PDF contains no selectable digital text. Optical Character Recognition (OCR) is required.")
    else:
        st.info("This agreement is ingested but has not yet completed full AI analysis. Click below to start the pipeline.")
        btn_txt = "Retry Analysis" if proc_status in {"failed", "partially_analyzed"} else "Launch Full AI Analysis"
        if st.button(btn_txt, type="primary"):
            with st.spinner("Extracting clauses, running Gemini classification, risk scoring, and benchmark RAG..."):
                try:
                    client.analyze_document(selected_id)
                    st.success("Analysis completed successfully!")
                    st.rerun()
                except APIError as exc:
                    st.error(exc.message)

# Direct Shortcut to Detailed Risk Assessment
if proc_status == "analyzed":
    col_jump1, col_jump2 = st.columns([3, 1])
    with col_jump2:
        if st.button("🛡️ Jump to Risk Assessment →", use_container_width=True):
            st.switch_page("pages/3_Risk_Analysis.py")

# Modern Tabs for Executive Summary, Contract Metadata, Classified Clauses, and Raw Pages
tab_summary, tab_metadata, tab_clauses, tab_pages = st.tabs(
    ["📋 Executive Legal Summary", "🔍 Contract Metadata", "⚖️ Classified Clauses", "📄 Raw Page Source Text"]
)

with tab_summary:
    if proc_status == "analyzed":
        try:
            analysis = client.get_analysis(selected_id)
            mode = analysis.get("analysis_mode", "deterministic_fallback")
            gemini_status = analysis.get("gemini_status", "missing_key")

            if analysis.get("fallback_used"):
                st.warning(
                    f"⚠️ Screening conducted via `{mode}` (Gemini status: `{gemini_status}`). "
                    f"Reason: {analysis.get('fallback_reason') or 'API unavailable'}. "
                    "Deterministic findings are pattern-based and distinct from generative Gemini advice."
                )

            st.markdown(
                f"""
                <div style="background:#F8FAFC; border:1px solid #E6EAF0; border-radius:10px; padding:0.75rem 1rem; margin-bottom:1rem; font-size:0.8rem; color:#748094; display:flex; justify-content:space-between; flex-wrap:wrap; gap:0.5rem;">
                    <div>Contract Classification: <strong style="color:#101B35;">{html.escape(analysis.get('detected_contract_type', 'General Agreement'))}</strong></div>
                    <div>Embedding Provider: <code>{html.escape(analysis.get('embedding_backend', 'N/A'))}</code></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown(
                f"""
                <div class="le-card" style="line-height:1.65; color:#172033; font-size:0.92rem;">
                    {analysis.get('executive_summary', 'No executive summary available.')}
                </div>
                """,
                unsafe_allow_html=True,
            )
        except APIError as exc:
            st.error(exc.message)
    else:
        st.info("Executive summary will be generated once contract analysis is run.")

with tab_metadata:
    if proc_status in ("analyzed", "partially_analyzed"):
        try:
            meta_resp = client.get_metadata(selected_id)
            meta_data = meta_resp.get("metadata") or {}
            if not meta_data:
                st.info("No structured metadata is recorded for this document.")
            else:
                source = meta_data.get("extraction_source", "deterministic_fallback")
                completeness = meta_data.get("completeness_score", 0.0)
                source_badge = "🤖 Gemini AI Extraction" if source == "gemini" else "⚙️ Deterministic Heuristic Extraction"

                st.markdown(
                    f"""
                    <div style="background:#F8FAFC; border:1px solid #E6EAF0; border-radius:10px; padding:0.75rem 1rem; margin-bottom:1.25rem; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.75rem;">
                        <div style="font-size:0.85rem; color:#475569;">
                            Extraction Engine: <strong style="color:#101B35;">{html.escape(source_badge)}</strong>
                        </div>
                        <div style="font-size:0.85rem; color:#475569;">
                            Completeness Score: <strong style="color:#0EA5E9;">{int(completeness * 100)}%</strong>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                field_display_names = [
                    ("contract_title_and_type", "Contract Title & Type"),
                    ("party_names_and_roles", "Parties & Roles"),
                    ("effective_date", "Effective Date"),
                    ("expiration_date", "Expiration Date"),
                    ("contract_duration", "Contract Duration"),
                    ("renewal_date_and_conditions", "Renewal Terms"),
                    ("contract_value", "Contract Value"),
                    ("payment_terms", "Payment Terms"),
                    ("governing_law_and_jurisdiction", "Governing Law"),
                    ("notice_period", "Notice Period"),
                    ("termination_conditions", "Termination Conditions"),
                    ("liability_limitations", "Liability Limitations"),
                    ("indemnification_terms", "Indemnification Terms"),
                    ("deliverables_and_responsibilities", "Key Deliverables"),
                    ("confidentiality_period", "Confidentiality Period"),
                    ("dispute_resolution_method", "Dispute Resolution"),
                ]

                col1, col2 = st.columns(2)
                for idx, (fkey, flabel) in enumerate(field_display_names):
                    target_col = col1 if idx % 2 == 0 else col2
                    fval = meta_data.get(fkey) or {}
                    val_text = fval.get("value")
                    is_missing = fval.get("is_missing", False) or val_text is None
                    is_verified = fval.get("verified", False)
                    quote = fval.get("source_quote")
                    page_no = fval.get("page_number")
                    para_no = fval.get("paragraph_index")
                    loc_str = f"Page {page_no}" if page_no else (f"DOCX Para {para_no}" if para_no else None)

                    with target_col:
                        with st.container(border=True):
                            top_col1, top_col2 = st.columns([2, 1])
                            with top_col1:
                                st.caption(flabel)
                            with top_col2:
                                if is_missing:
                                    st.markdown("<span style='font-size:0.75rem; color:#94A3B8; float:right;'>⚪ Missing</span>", unsafe_allow_html=True)
                                elif is_verified:
                                    st.markdown("<span style='font-size:0.75rem; color:#16A36A; font-weight:700; float:right;'>🟢 Verified</span>", unsafe_allow_html=True)
                                else:
                                    st.markdown("<span style='font-size:0.75rem; color:#D97706; font-weight:700; float:right;'>🟡 Unverified</span>", unsafe_allow_html=True)

                            if is_missing:
                                st.markdown("<em style='color:#94A3B8; font-size:0.85rem;'>Not specified in contract</em>", unsafe_allow_html=True)
                            else:
                                if isinstance(val_text, list):
                                    st.markdown(f"**{', '.join(str(v) for v in val_text)}**")
                                else:
                                    st.markdown(f"**{val_text}**")

                            if loc_str:
                                st.markdown(f"<span style='font-size:0.72rem; color:#64748B;'>📍 {loc_str}</span>", unsafe_allow_html=True)

                            if quote:
                                with st.expander("📖 Verbatim Evidence Quote"):
                                    st.caption(f'"{html.escape(quote)}"')
        except APIError as exc:
            st.error(exc.message)
    else:
        st.info("Run contract analysis above to extract and verify structured contract metadata.")


with tab_clauses:
    if proc_status == "analyzed":
        try:
            clauses_resp = client.get_clauses(selected_id)
            render_clause_viewer(clauses_resp.get("clauses", []))
        except APIError as exc:
            st.error(exc.message)
    else:
        st.info("Run contract analysis above to segment and classify the agreement's clauses.")

with tab_pages:
    pages = extracted.get("pages", [])
    if not pages:
        st.info("No raw extracted text is recorded for this document.")
    else:
        for idx, page in enumerate(pages, start=1):
            pno = page.get("page_number")
            title_lbl = f"Page {pno}" if pno is not None else "DOCX Paragraphs (Flowing Layout)"
            with st.expander(f"📄 {title_lbl}", expanded=(idx == 1)):
                if page.get("headings"):
                    st.caption("Detected Section Headings: " + " | ".join(page["headings"]))
                st.text_area(
                    title_lbl,
                    value=page.get("text", ""),
                    height=200,
                    disabled=True,
                    key=f"page_txt_{selected_id}_{idx}",
                    label_visibility="collapsed",
                )

render_disclaimer_footer()
