"""Page 8: Enterprise Platform Configuration & Security Settings."""

import html
import streamlit as st

from frontend.components.risk_cards import render_kpi_card
from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.utils.api_client import APIError, DEFAULT_API_BASE_URL


client = get_api_client()
health, docs, selected_id = render_sidebar_context(client)

render_page_header(
    title="Platform Settings",
    subtitle="Configure API endpoints, inspect Gemini 2.5 AI telemetry, rebuild FAISS vector stores, and verify privacy controls.",
    category="Administration",
    active_doc_name=selected_id,
)

tab_conn, tab_ai, tab_rag, tab_sec = st.tabs(
    ["🌐 API & Backend Connection", "🤖 AI & Model Telemetry", "📚 FAISS Vector Index", "🔒 Security & Compliance"]
)

# TAB 1: API & Backend Connection
with tab_conn:
    st.markdown(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">Backend API Configuration</h3>
                <p class="le-section-subtitle">Manage connection to the FastAPI microservice</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    current_url = st.session_state.get("api_base_url", DEFAULT_API_BASE_URL)
    new_url = st.text_input("FastAPI Base Endpoint URL", value=current_url, help="Default is http://127.0.0.1:8000")

    if st.button("Save & Validate Connection", type="primary"):
        st.session_state["api_base_url"] = new_url.strip().rstrip("/")
        st.rerun()

    if health:
        st.markdown(
            f"""
            <div class="le-card" style="border-left:4px solid #16A36A; margin-top:1rem;">
                <div style="font-size:0.95rem; font-weight:700; color:#166534; margin-bottom:0.25rem;">
                    ✓ Backend Live & Synchronized
                </div>
                <div style="font-size:0.84rem; color:#14532D;">
                    Connected to <strong>{html.escape(health.get('app', 'LegalEase'))}</strong> version <code>{html.escape(health.get('version', '1.0'))}</code>.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            render_kpi_card("Connected Service", health.get("app", "LegalEase"), "FastAPI Server", "#101B35", icon="🚀")
        with c2:
            render_kpi_card("Ingested Contracts", len(docs), "SQLite Database", "#356AE6", icon="📁")
        with c3:
            render_kpi_card("API Status", "Healthy", "Response code 200", "#16A36A", icon="✓")
    else:
        st.error("Backend is currently unreachable. Ensure FastAPI server is running on the specified host/port.")

# TAB 2: AI & Model Telemetry
with tab_ai:
    st.markdown(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">GenAI Intelligence Engine</h3>
                <p class="le-section-subtitle">Real-time status of Google Gemini and offline fallback heuristics</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    gemini_on = health.get("gemini_configured", False) if health else False

    if gemini_on:
        st.markdown(
            """
            <div class="le-card" style="border-left:4px solid #16A36A;">
                <div style="font-size:0.95rem; font-weight:700; color:#166534; margin-bottom:0.25rem;">
                    ✓ Google Gemini 2.5 Flash Online
                </div>
                <div style="font-size:0.84rem; color:#14532D;">
                    The server has loaded a valid Google Gemini API key. Structured JSON output, multi-turn contract classification,
                    and generative risk assessments are enabled with automatic transient 429 rate-limit backoff.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="le-card" style="border-left:4px solid #E69A32;">
                <div style="font-size:0.95rem; font-weight:700; color:#92400E; margin-bottom:0.25rem;">
                    ⚠️ Operating in Deterministic Screening Fallback Mode
                </div>
                <div style="font-size:0.84rem; color:#78350F;">
                    No <code>GEMINI_API_KEY</code> was detected in the backend <code>.env</code> file. LegalEase continues to operate using
                    deterministic rule-based pattern matching, regex classification, and weighted heuristic risk scoring.
                    All fallback findings are transparently flagged as non-AI outputs.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <div class="le-card">
            <div style="font-size:0.84rem; font-weight:700; color:#101B35; margin-bottom:0.4rem;">
                Model Architecture & Quota Safeguards
            </div>
            <ul style="font-size:0.82rem; color:#748094; margin:0; padding-left:1.2rem; line-height:1.6;">
                <li><strong>Model Tier:</strong> <code>gemini-2.5-flash</code> with temperature 0.1 for high reproducibility.</li>
                <li><strong>Pydantic Enforced:</strong> All LLM responses are validated via strict JSON Schema.</li>
                <li><strong>Batch Optimization:</strong> Comparison and classification calls are batched to preserve free-tier request limits.</li>
                <li><strong>Key Privacy:</strong> API keys reside exclusively in server-side environment variables and are never transmitted to client browsers.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

# TAB 3: FAISS Vector Index
with tab_rag:
    st.markdown(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">FAISS Vector Store & Benchmark Knowledge Base</h3>
                <p class="le-section-subtitle">Manage reference clause embeddings and similarity index</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div style="font-size:0.84rem; color:#748094; margin-bottom:1rem; line-height:1.5;">
            LegalEase embeds reference templates from <code>data/reference_templates/</code> using 
            <code>all-MiniLM-L6-v2</code> (or deterministic hashed embeddings when offline). If you update template files,
            trigger an index re-sync below.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("🔄 Rebuild FAISS Reference Index Now", type="primary"):
        with st.spinner("Extracting template clauses and building FAISS vector index..."):
            try:
                res = client.rebuild_templates()
                is_sem = res.get("is_semantic_embeddings", False)
                emb_desc = res.get("embedding_label") or res.get("embedding_backend")
                st.success(
                    f"Successfully rebuilt FAISS index with **{res['indexed_clauses']}** reference clauses "
                    f"(Backend: `{emb_desc}`, Dimension: {res.get('embedding_dimension', 384)})."
                )
                if not is_sem:
                    st.info(
                        "Currently using deterministic hash embeddings. To activate deep semantic embeddings, "
                        "ensure the SentenceTransformers model cache is present."
                    )
            except APIError as exc:
                st.error(exc.message)

# TAB 4: Security & Compliance
with tab_sec:
    st.markdown(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">Enterprise Security & Compliance Safeguards</h3>
                <p class="le-section-subtitle">Architectural isolation and data protection practices</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="le-card" style="margin-bottom:0.85rem;">
            <div style="font-size:0.9rem; font-weight:700; color:#101B35; margin-bottom:0.35rem;">
                🛡️ Upload Validation & DoS Hardening
            </div>
            <div style="font-size:0.82rem; color:#748094; line-height:1.55;">
                Uploads are inspected in streaming chunks, enforcing a strict 15 MB limit before memory allocation.
                Magic bytes verification ensures extension spoofing is rejected. Encrypted PDFs and zip-bomb DOCX files are blocked.
            </div>
        </div>

        <div class="le-card" style="margin-bottom:0.85rem;">
            <div style="font-size:0.9rem; font-weight:700; color:#101B35; margin-bottom:0.35rem;">
                🔒 Untrusted Input Isolation & Prompt Safety
            </div>
            <div style="font-size:0.82rem; color:#748094; line-height:1.55;">
                All contract text is encapsulated within secure XML tags and treated as untrusted user data.
                System prompts explicitly forbid contract text from overriding system review policies or security rules.
            </div>
        </div>

        <div class="le-card" style="margin-bottom:0.85rem;">
            <div style="font-size:0.9rem; font-weight:700; color:#101B35; margin-bottom:0.35rem;">
                🗑️ Permanent Data Destruction & Path Containment
            </div>
            <div style="font-size:0.82rem; color:#748094; line-height:1.55;">
                Uploaded files and generated reports reside in restricted local directory hierarchies.
                Deleting an active contract from the Dashboard completely purges the source document, extracted pages,
                clause database rows, and compiled PDF reports.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

render_disclaimer_footer()
