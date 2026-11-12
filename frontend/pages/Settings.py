"""Page 8: Platform Configuration, Reference Index & Security Settings."""

import streamlit as st

from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.utils.api_client import APIError, DEFAULT_API_BASE_URL


render_page_header(
    "Settings",
    "Configure backend API connection, inspect Gemini AI availability, and manage FAISS reference templates.",
)

client = get_api_client()
health, docs, _ = render_sidebar_context(client)

st.subheader("Backend Connection")
current_url = st.session_state.get("api_base_url", DEFAULT_API_BASE_URL)
new_url = st.text_input("FastAPI Base URL", value=current_url)
if st.button("Save & Test Connection"):
    st.session_state["api_base_url"] = new_url.strip().rstrip("/")
    st.rerun()

if health:
    st.success(f"Connected to {health.get('app')} v{health.get('version')}")
    c1, c2 = st.columns(2)
    c1.metric("Gemini API Configured", "Yes" if health.get("gemini_configured") else "No (Fallback Mode)")
    c2.metric("Stored Documents", len(docs))
    if not health.get("gemini_configured"):
        st.warning(
            "GEMINI_API_KEY is not set in the backend `.env` file. LegalEase is currently operating in "
            "deterministic screening fallback mode and explicitly marks all fallback outputs."
        )

st.divider()
st.subheader("FAISS Reference Template Vector Store")
st.caption(
    "Rebuild the FAISS similarity index from `data/reference_templates/` after adding or editing "
    "illustrative NDA, Service Agreement, Employment, or Partnership templates."
)
if st.button("Rebuild FAISS Reference Index", type="primary"):
    with st.spinner("Indexing reference templates..."):
        try:
            res = client.rebuild_templates()
            st.success(
                f"Rebuilt FAISS index with **{res['indexed_clauses']}** reference clauses "
                f"(embedding backend: `{res['embedding_backend']}`)."
            )
        except APIError as exc:
            st.error(exc.message)

st.divider()
st.subheader("Security & Privacy Safeguards")
st.markdown(
    """
    - API keys are loaded server-side from `.env` and never transmitted to the browser.
    - Uploaded files are checked for allowed extensions (`.pdf`, `.docx`), magic bytes, size limits, and PDF encryption.
    - Uploaded documents are stored outside public static URLs and can be permanently deleted from the Dashboard.
    - Contract text is wrapped as untrusted data and separated from trusted LLM system prompts.
    """
)

render_disclaimer_footer()

