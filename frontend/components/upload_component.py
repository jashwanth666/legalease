"""Contract upload, file preview, and user-initiated LangGraph analysis component."""

from datetime import datetime, timezone
import html
import streamlit as st

from frontend.utils.api_client import APIError, LegalEaseAPIClient


def _clean_html(raw_html: str) -> str:
    """Strip leading whitespace on each line so Markdown parser never renders HTML as an indented code block."""
    lines = [line.strip() for line in raw_html.splitlines() if line.strip()]
    return "\n".join(lines)


def _format_size(num_bytes: int) -> str:
    """Format bytes into readable KB/MB."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def render_upload_workflow(client: LegalEaseAPIClient) -> None:
    """Render modern SaaS drag-and-drop upload zone, document preview, and confirmation workflow."""
    upload_zone_html = """
    <div style="background:#FFFFFF; border:2px dashed #CBD5E1; border-radius:14px; padding:2rem; text-align:center; margin-bottom:1.25rem;">
        <div style="font-size:2.4rem; margin-bottom:0.5rem;">📂</div>
        <div style="font-size:1.15rem; font-weight:700; color:#101B35; margin-bottom:0.25rem;">
            Upload Legal Agreement for AI Screening
        </div>
        <div style="font-size:0.85rem; color:#748094; max-width:480px; margin:0 auto 1rem auto;">
            Select or drag a commercial contract in PDF or DOCX format. Scanned PDFs without text layers will be detected and flagged.
        </div>
        <div style="display:flex; justify-content:center; gap:0.5rem; flex-wrap:wrap;">
            <span style="background:#EFF6FF; color:#1D4ED8; font-size:0.75rem; font-weight:700; padding:0.2rem 0.6rem; border-radius:999px;">PDF SUPPORTED</span>
            <span style="background:#EFF6FF; color:#1D4ED8; font-size:0.75rem; font-weight:700; padding:0.2rem 0.6rem; border-radius:999px;">DOCX SUPPORTED</span>
            <span style="background:#F1F5F9; color:#475569; font-size:0.75rem; font-weight:700; padding:0.2rem 0.6rem; border-radius:999px;">MAX 15 MB</span>
            <span style="background:#ECFDF5; color:#065F46; font-size:0.75rem; font-weight:700; padding:0.2rem 0.6rem; border-radius:999px;">ENCRYPTED STORAGE</span>
        </div>
    </div>
    """
    st.markdown(_clean_html(upload_zone_html), unsafe_allow_html=True)

    uploaded_file = st.file_uploader(
        "Upload File",
        type=["pdf", "docx"],
        help="Upload standard PDF or DOCX agreements. File size limit is 15 MB.",
        label_visibility="collapsed",
    )

    if uploaded_file is not None:
        raw_bytes = uploaded_file.getvalue()
        ext = uploaded_file.name.rsplit(".", 1)[-1].upper() if "." in uploaded_file.name else "UNKNOWN"
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        file_card_html = f"""
        <div class="le-card" style="border:1px solid #356AE6; background:#F8FAFF; margin-bottom:1rem;">
            <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:#356AE6; margin-bottom:0.4rem;">
                Ready for Ingestion
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
                <div>
                    <span style="font-size:1.1rem; font-weight:700; color:#101B35;">{html.escape(uploaded_file.name)}</span>
                    <div style="font-size:0.8rem; color:#748094; margin-top:0.2rem;">
                        Type: <strong>{ext}</strong> &bull; Size: <strong>{_format_size(len(raw_bytes))}</strong> &bull; Selected: {now_str}
                    </div>
                </div>
                <span style="background:#ECFDF5; color:#065F46; border:1px solid #A7F3D0; padding:0.2rem 0.6rem; border-radius:999px; font-size:0.75rem; font-weight:700;">
                    Ready
                </span>
            </div>
        </div>
        """
        st.markdown(_clean_html(file_card_html), unsafe_allow_html=True)

        if st.button("Confirm & Upload Contract to Secure Vault", type="primary", use_container_width=True):
            with st.spinner("Extracting text layers, checking integrity, and indexing document..."):
                try:
                    resp = client.upload_document(
                        filename=uploaded_file.name,
                        content=raw_bytes,
                        content_type=uploaded_file.type or "application/octet-stream",
                    )
                    st.session_state["selected_document_id"] = resp["document_id"]
                    st.session_state["last_upload_response"] = resp
                    loc_summary = (
                        f"{resp['page_count']} pages indexed"
                        if resp["file_type"] == "pdf"
                        else "DOCX paragraphs indexed"
                    )
                    st.success(f"Successfully uploaded **{resp['filename']}** (`{resp['document_id']}`) &mdash; {loc_summary}!")
                    st.rerun()
                except APIError as exc:
                    if exc.status_code == 401 or "does not exist" in str(exc.message).lower():
                        st.session_state.pop("auth_token", None)
                        st.session_state.pop("user", None)
                        st.session_state.pop("selected_document_id", None)
                        client.set_token(None)
                        st.rerun()
                    st.error(f"Upload failed: {exc.message}")

    # Active Document Status & Analysis Confirmation
    last_upload = st.session_state.get("last_upload_response")
    selected_id = st.session_state.get("selected_document_id")

    if selected_id:
        try:
            doc_detail = client.get_document(selected_id)
            doc = doc_detail["document"]
        except APIError:
            doc = last_upload if (last_upload and last_upload.get("document_id") == selected_id) else None

        if doc:
            proc_status = doc.get("processing_status", "uploaded")
            status_colors = {
                "uploaded": "#356AE6",
                "processing": "#E69A32",
                "analyzed": "#16A36A",
                "partially_analyzed": "#E87536",
                "failed": "#DC4545",
            }
            status_color = status_colors.get(proc_status, "#748094")

            active_card_html = f"""
            <div class="le-card" style="margin-top:1.5rem; border-top:3px solid {status_color};">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem; margin-bottom:0.75rem;">
                    <div>
                        <div style="font-size:0.72rem; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:#748094;">
                            Active Contract in Vault
                        </div>
                        <div style="font-size:1.15rem; font-weight:700; color:#101B35;">
                            {html.escape(doc['filename'])}
                        </div>
                    </div>
                    <div style="display:flex; align-items:center; gap:0.5rem;">
                        <span style="background:{status_color}18; color:{status_color}; border:1px solid {status_color}40; padding:0.25rem 0.65rem; border-radius:999px; font-size:0.75rem; font-weight:700; text-transform:uppercase;">
                            {html.escape(proc_status)}
                        </span>
                    </div>
                </div>
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:0.75rem; font-size:0.8rem; color:#748094; padding:0.6rem 0; border-top:1px solid #F1F4F9; border-bottom:1px solid #F1F4F9;">
                    <div>ID: <strong style="color:#101B35;">{html.escape(doc['document_id'])}</strong></div>
                    <div>Format: <strong style="color:#101B35;">{html.escape(doc['file_type'].upper())}</strong></div>
                    <div>Pages/Layout: <strong style="color:#101B35;">{doc.get('page_count', 0) if doc['file_type'] == 'pdf' else 'DOCX Paras'}</strong></div>
                    <div>Mode: <strong style="color:#101B35;">{html.escape(doc.get('analysis_mode') or 'Pending')}</strong></div>
                </div>
            </div>
            """
            st.markdown(_clean_html(active_card_html), unsafe_allow_html=True)

            if doc.get("last_error"):
                st.error(f"Previous analysis reported an error: {doc['last_error']}")

            if doc.get("ocr_required"):
                st.warning(
                    "⚠️ No selectable text detected in this PDF. It appears to be a scanned document. "
                    "OCR text recognition is required before semantic clause analysis can proceed."
                )
            else:
                is_analyzed = proc_status == "analyzed"
                btn_label = "Re-analyze Contract" if is_analyzed else ("Retry Analysis" if proc_status in {"failed", "partially_analyzed"} else "Run AI Contract Analysis")

                notice_html = """
                <div style="font-size:0.84rem; color:#748094; margin:0.75rem 0 0.5rem 0;">
                    To respect token quotas and ensure full human control, LegalEase requires explicit user confirmation
                    to launch the LangGraph multi-stage review (splitting, categorization, risk scoring, benchmark RAG, and PDF generation).
                </div>
                """
                st.markdown(_clean_html(notice_html), unsafe_allow_html=True)

                if st.button(btn_label, type="primary", use_container_width=True):
                    progress_bar = st.progress(0.1, text="Queuing contract intelligence pipeline...")
                    try:
                        client.analyze_document(selected_id)
                        import time
                        max_wait_seconds = 120
                        start_time = time.time()
                        last_logged_stage = None

                        while time.time() - start_time < max_wait_seconds:
                            status_resp = client.get_analysis_status(selected_id)
                            current_stage = status_resp.get("current_stage")
                            progress_pct = float(status_resp.get("progress_percent", 10.0))
                            is_complete = status_resp.get("is_complete", False)
                            has_failed = status_resp.get("has_failed", False)

                            if current_stage != last_logged_stage:
                                stage_label = current_stage.replace("_", " ").title() if current_stage else "Processing"
                                progress_bar.progress(int(progress_pct), text=f"Stage: {stage_label} ({int(progress_pct)}%)")
                                last_logged_stage = current_stage

                            if is_complete:
                                progress_bar.progress(100, text="Analysis Complete! Rendering Intelligence...")
                                st.success(f"Analysis completed successfully in {int(time.time() - start_time)} seconds!")
                                time.sleep(0.5)
                                st.rerun()

                            if has_failed:
                                err = status_resp.get("error_message", "Unknown pipeline failure")
                                progress_bar.empty()
                                st.error(f"Analysis pipeline failed: {err}")
                                break

                            time.sleep(1.0)
                        else:
                            st.warning("Analysis is taking longer than usual. You can monitor progress on the Document Analysis page.")
                    except APIError as exc:
                        progress_bar.empty()
                        st.error(f"Failed to initiate analysis: {exc.message}")
