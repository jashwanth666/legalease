"""Contract upload and explicit analysis confirmation component."""

from datetime import datetime, timezone
import streamlit as st

from frontend.utils.api_client import APIError, LegalEaseAPIClient


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def render_upload_workflow(client: LegalEaseAPIClient) -> None:
    """Render PDF/DOCX upload widget, document metadata, and manual Analyze button."""
    uploaded_file = st.file_uploader(
        "Select a Legal Agreement (PDF or DOCX)",
        type=["pdf", "docx"],
        help="Maximum upload size is enforced by the backend (default 15 MB). Encrypted PDFs are rejected.",
    )

    if uploaded_file is not None:
        raw_bytes = uploaded_file.getvalue()
        ext = uploaded_file.name.rsplit(".", 1)[-1].upper() if "." in uploaded_file.name else "UNKNOWN"
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Filename", uploaded_file.name)
        col2.metric("File Type", ext)
        col3.metric("File Size", _format_size(len(raw_bytes)))
        col4.metric("Selected At", now_str)

        if st.button("Upload Contract to Secure Storage", type="primary", use_container_width=True):
            with st.spinner("Validating file signature, storing securely, and extracting text..."):
                try:
                    resp = client.upload_document(
                        filename=uploaded_file.name,
                        content=raw_bytes,
                        content_type=uploaded_file.type or "application/octet-stream",
                    )
                    st.session_state["selected_document_id"] = resp["document_id"]
                    st.session_state["last_upload_response"] = resp
                    loc_summary = (
                        f"{resp['page_count']} pages"
                        if resp["file_type"] == "pdf"
                        else "DOCX paragraphs indexed"
                    )
                    st.success(f"Uploaded successfully as **{resp['document_id']}** ({loc_summary}).")
                    st.rerun()
                except APIError as exc:
                    st.error(f"Upload failed: {exc.message}")

    last_upload = st.session_state.get("last_upload_response")
    selected_id = st.session_state.get("selected_document_id")

    if selected_id:
        try:
            doc_detail = client.get_document(selected_id)
            doc = doc_detail["document"]
        except APIError:
            doc = last_upload if (last_upload and last_upload.get("document_id") == selected_id) else None

        if doc:
            st.divider()
            st.subheader(f"Ready for Review: {doc['filename']} ({doc['document_id']})")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Document ID", doc["document_id"])
            m2.metric("Format", doc["file_type"].upper())
            m3.metric(
                "Pages" if doc["file_type"] == "pdf" else "Layout",
                doc.get("page_count", 0) if doc["file_type"] == "pdf" else "DOCX Paras",
            )
            proc_status = doc.get("processing_status", "uploaded")
            m4.metric("Status", proc_status.upper())

            if doc.get("last_error"):
                st.error(f"Previous run reported an error: {doc['last_error']}")

            if doc.get("ocr_required"):
                st.warning(
                    "No usable selectable text was detected in this PDF. It appears to be a scanned "
                    "document; OCR is required (planned as a future enhancement)."
                )
            else:
                st.info(
                    "AI analysis will NOT start automatically. Click **Analyze Contract** below to run "
                    "clause splitting, classification, risk scoring, RAG template comparison, and PDF report generation."
                )
                btn_label = (
                    "Retry Contract Analysis"
                    if proc_status in {"failed", "partially_analyzed"}
                    else "Analyze Contract"
                )
                if st.button(btn_label, type="primary", use_container_width=True):
                    with st.spinner(
                        "Running LangGraph multi-stage analysis (splitting, classification, "
                        "risk scoring, FAISS comparison, evidence verification, PDF report)..."
                    ):
                        try:
                            result = client.analyze_document(doc["document_id"])
                            if result.get("fallback_used"):
                                st.warning(
                                    f"Analysis completed in `{result.get('analysis_mode')}` mode "
                                    f"(Gemini status: `{result.get('gemini_status')}` — {result.get('fallback_reason')})."
                                )
                            st.success(
                                f"Analysis complete! Overall Illustrative Risk Score: "
                                f"**{result['overall_risk_score']}/100 ({result['overall_risk_level'].replace('_', ' ').upper()})**."
                            )
                        except APIError as exc:
                            st.error(f"Analysis failed: {exc.message}")

