"""Contract upload, file preview, and user-initiated LangGraph analysis component."""

from datetime import datetime, timezone
import html
import streamlit as st

from frontend.utils.api_client import APIError, LegalEaseAPIClient


def _format_size(num_bytes: int) -> str:
    """Format bytes into readable KB/MB."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def render_upload_workflow(client: LegalEaseAPIClient) -> None:
    """Render modern SaaS drag-and-drop upload zone, document preview, and confirmation workflow."""
    st.markdown(
        """
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
        """,
        unsafe_allow_html=True,
    )

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

        st.markdown(
            f"""
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
            """,
            unsafe_allow_html=True,
        )

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

            st.markdown(
                f"""
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
                """,
                unsafe_allow_html=True,
            )

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

                st.markdown(
                    """
                    <div style="font-size:0.84rem; color:#748094; margin:0.75rem 0 0.5rem 0;">
                        To respect token quotas and ensure full human control, LegalEase requires explicit user confirmation
                        to launch the LangGraph multi-stage review (splitting, categorization, risk scoring, benchmark RAG, and PDF generation).
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if st.button(btn_label, type="primary", use_container_width=True):
                    progress_bar = st.progress(0.1, text="Queuing contract intelligence pipeline...")
                    try:
                        client.analyze_document(selected_id)
                        import time
                        max_wait_seconds = 120
                        start_time = time.time()
                        while time.time() - start_time < max_wait_seconds:
                            time.sleep(1.5)
                            status_data = client.get_status(selected_id)
                            curr_status = status_data.get("processing_status", "processing")
                            curr_pct = float(status_data.get("progress_percent", 50)) / 100.0
                            stage_desc = status_data.get("stage", "Analyzing contract...")
                            progress_bar.progress(min(max(curr_pct, 0.1), 1.0), text=f"Stage: {stage_desc}")

                            if curr_status == "analyzed":
                                progress_bar.progress(1.0, text="Analysis complete!")
                                st.success("Analysis complete! Review the findings in the Dashboard or Risk Assessment tab.")
                                st.rerun()
                                break
                            elif curr_status in {"failed", "partially_analyzed"}:
                                err = status_data.get("last_error") or "Analysis completed with warnings or failures."
                                if curr_status == "partially_analyzed":
                                    st.warning(f"Analysis partially completed: {err}")
                                else:
                                    st.error(f"Analysis failed: {err}")
                                st.rerun()
                                break
                    except APIError as exc:
                        st.error(f"Analysis failed: {exc.message}")
