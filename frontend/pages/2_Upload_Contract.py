"""Page 2: Contract Upload & Ingestion Portal."""

import html
from pathlib import Path
import streamlit as st

from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.components.upload_component import render_upload_workflow
from frontend.utils.api_client import APIError


client = get_api_client()
health, docs, selected_id = render_sidebar_context(client)

render_page_header(
    title="Upload Contract",
    subtitle="Securely ingest commercial agreements for multi-page extraction, automated clause splitting, and AI screening.",
    category="Ingestion",
    active_doc_name=selected_id,
)

if health is None:
    st.error("Backend offline. Please start or connect to the LegalEase API server.")
    st.stop()

# Main Upload Workflow Component (includes dropzone, preview, confirmation, and analysis trigger)
render_upload_workflow(client)

# Demo Sample Contracts Showcase
st.markdown(
    """
    <div class="le-section-header" style="margin-top:2rem;">
        <div>
            <h3 class="le-section-title">Preloaded Benchmark Contracts</h3>
            <p class="le-section-subtitle">Load an authentic sample agreement to immediately explore the end-to-end intelligence pipeline</p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

sample_dir = Path(__file__).resolve().parent.parent.parent / "data" / "sample_contracts"

sc1, sc2 = st.columns(2)

# Sample NDA Card
with sc1:
    nda_path = sample_dir / "sample_nda.pdf"
    st.markdown(
        """
        <div class="le-card" style="height:100%; border-top:3px solid #356AE6;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
                <span style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:#356AE6;">Sample Agreement</span>
                <span style="background:#EFF6FF; color:#1D4ED8; font-size:0.72rem; font-weight:700; padding:0.15rem 0.5rem; border-radius:999px;">PDF &bull; 2 Pages</span>
            </div>
            <div style="font-size:1.05rem; font-weight:700; color:#101B35; margin-bottom:0.25rem;">
                Mutual Non-Disclosure Agreement (NDA)
            </div>
            <div style="font-size:0.82rem; color:#748094; margin-bottom:1rem; line-height:1.45;">
                Standard bilateral NDA containing confidentiality definitions, exclusions, non-compete provisions, and jurisdiction clauses.
            </div>
        """,
        unsafe_allow_html=True,
    )
    if nda_path.exists():
        if st.button("📥 Load Sample NDA", key="btn_load_sample_nda", use_container_width=True):
            try:
                resp = client.upload_document(
                    filename="sample_nda.pdf",
                    content=nda_path.read_bytes(),
                    content_type="application/pdf",
                )
                st.session_state["selected_document_id"] = resp["document_id"]
                st.session_state["last_upload_response"] = resp
                st.success(f"Loaded sample NDA as `{resp['document_id']}`. Ready for analysis!")
                st.rerun()
            except APIError as exc:
                st.error(exc.message)
    st.markdown("</div>", unsafe_allow_html=True)

# Sample Service Agreement Card
with sc2:
    srv_path = sample_dir / "sample_service_agreement.pdf"
    st.markdown(
        """
        <div class="le-card" style="height:100%; border-top:3px solid #E87536;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
                <span style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:#E87536;">Complex Agreement</span>
                <span style="background:#FFF7ED; color:#C2410C; font-size:0.72rem; font-weight:700; padding:0.15rem 0.5rem; border-radius:999px;">PDF &bull; 3 Pages</span>
            </div>
            <div style="font-size:1.05rem; font-weight:700; color:#101B35; margin-bottom:0.25rem;">
                Master Services Agreement (MSA)
            </div>
            <div style="font-size:0.82rem; color:#748094; margin-bottom:1rem; line-height:1.45;">
                Enterprise vendor agreement with stringent liability caps ($100), unilateral indemnity, AS-IS warranties, and 90-day auto-renewal.
            </div>
        """,
        unsafe_allow_html=True,
    )
    if srv_path.exists():
        if st.button("📥 Load Sample Service Agreement", key="btn_load_sample_srv", use_container_width=True):
            try:
                resp = client.upload_document(
                    filename="sample_service_agreement.pdf",
                    content=srv_path.read_bytes(),
                    content_type="application/pdf",
                )
                st.session_state["selected_document_id"] = resp["document_id"]
                st.session_state["last_upload_response"] = resp
                st.success(f"Loaded Master Services Agreement as `{resp['document_id']}`. Ready for analysis!")
                st.rerun()
            except APIError as exc:
                st.error(exc.message)
    st.markdown("</div>", unsafe_allow_html=True)

render_disclaimer_footer()
