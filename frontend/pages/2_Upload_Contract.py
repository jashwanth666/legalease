"""Page 2: Contract Upload & Confirmation Workflow."""

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


render_page_header(
    "Upload Contract",
    "Securely upload PDF or Word (.docx) agreements for text extraction and user-confirmed analysis.",
)

client = get_api_client()
health, _, _ = render_sidebar_context(client)

if health is None:
    st.stop()

render_upload_workflow(client)

st.divider()
st.subheader("Demo Sample Contracts")
st.caption("Quickly load one of the included sample agreements to test the full end-to-end workflow.")

sample_dir = Path(__file__).resolve().parent.parent.parent / "data" / "sample_contracts"
col1, col2 = st.columns(2)

for col, fname, label in [
    (col1, "sample_nda.pdf", "Load Sample NDA (PDF)"),
    (col2, "sample_service_agreement.pdf", "Load Sample Service Agreement (PDF)"),
]:
    sample_path = sample_dir / fname
    with col:
        if sample_path.exists() and st.button(label, use_container_width=True):
            try:
                resp = client.upload_document(
                    filename=fname,
                    content=sample_path.read_bytes(),
                    content_type="application/pdf",
                )
                st.session_state["selected_document_id"] = resp["document_id"]
                st.session_state["last_upload_response"] = resp
                st.success(f"Loaded {fname} as **{resp['document_id']}**.")
                st.rerun()
            except APIError as exc:
                st.error(exc.message)

render_disclaimer_footer()

