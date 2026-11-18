"""Page 8: Enterprise Platform Configuration & Security Settings."""

import html
import streamlit as st

from frontend.components.risk_cards import clean_html, render_kpi_card
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

    user = st.session_state.get("user") or {}
    user_role = user.get("role", "employee")
    is_admin = user_role == "admin"

    if not is_admin:
        st.info("ℹ️ Rebuilding reference templates requires the `admin` role. Your current role is: `" + user_role + "`.")
    if st.button("🔄 Rebuild FAISS Reference Index Now", type="primary", disabled=not is_admin):
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

    curr_user = st.session_state.get("user") or {}
    if curr_user:
        st.markdown(
            f"""
            <div class="le-card" style="border-left:4px solid #356AE6; background:#F8FAFC; margin-bottom:1rem;">
                <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:#356AE6; margin-bottom:0.25rem;">
                    Active Session & Tenant Authorization
                </div>
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:0.5rem; font-size:0.82rem; color:#172033; margin-top:0.5rem;">
                    <div>User: <strong>{html.escape(curr_user.get('full_name', 'N/A'))}</strong></div>
                    <div>Email: <strong>{html.escape(curr_user.get('email', 'N/A'))}</strong></div>
                    <div>Role: <code>{html.escape(curr_user.get('role', 'N/A'))}</code></div>
                    <div>Tenant / Org ID: <code>{html.escape(curr_user.get('tenant_id', 'default_tenant'))}</code></div>
                    <div>Session Token: <span style="color:#16A36A; font-weight:600;">RFC 7519 HS256 Verified</span></div>
                    <div>Isolation: <span style="color:#16A36A; font-weight:600;">Strict Tenant Boundary</span></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if curr_user.get("role") == "admin":
            with st.expander("👥 Organization Team & Role Management (Admin Only)", expanded=False):
                st.markdown("##### Provision New Workspace Team Member")
                col_u1, col_u2 = st.columns(2)
                with col_u1:
                    new_u_email = st.text_input("User Email", key="admin_add_email", placeholder="reviewer@firm.com")
                    new_u_name = st.text_input("Full Name", key="admin_add_name", placeholder="Alice Legal")
                with col_u2:
                    new_u_pw = st.text_input("Initial Password", type="password", key="admin_add_pw", placeholder="••••••••")
                    new_u_role = st.selectbox(
                        "Assigned Role",
                        options=["legal_reviewer", "employee", "admin"],
                        format_func=lambda r: {"admin": "Admin", "legal_reviewer": "Legal Reviewer", "employee": "Employee"}.get(r, r),
                        key="admin_add_role",
                    )
                if st.button("Provision Account in Tenant", type="primary", key="btn_provision_user"):
                    if not new_u_email or not new_u_pw:
                        st.error("Email and password are required.")
                    else:
                        try:
                            client.create_tenant_user(
                                email=new_u_email.strip(),
                                password=new_u_pw,
                                full_name=new_u_name.strip() or None,
                                role=new_u_role,
                            )
                            st.success(f"Successfully provisioned user {new_u_email} with role {new_u_role}!")
                            st.rerun()
                        except APIError as exc:
                            st.error(exc.message)

                st.markdown("<hr style='margin:1rem 0; opacity:0.15;' />", unsafe_allow_html=True)
                st.markdown("##### Existing Workspace Users")
                try:
                    users_list = client.list_tenant_users()
                    user_rows = [
                        {"ID": u["id"], "Full Name": u.get("full_name") or "N/A", "Email": u["email"], "Role": u["role"].upper(), "Status": "Active" if u["is_active"] else "Inactive"}
                        for u in users_list
                    ]
                    st.dataframe(user_rows, use_container_width=True, hide_index=True)

                    manageable = [u for u in users_list if u["id"] != current_user.get("id")]
                    if manageable:
                        st.markdown("###### Manage Team Member Account Status")
                        col_u, col_act, col_btn = st.columns([2, 1, 1])
                        with col_u:
                            selected_user_label = st.selectbox(
                                "Select Team Member",
                                options=[f"{u['email']} ({u['role']})" for u in manageable],
                                key="sb_manage_user",
                            )
                        with col_act:
                            new_status = st.selectbox("Account Status", ["Active", "Deactivate"], key="sb_user_status")
                        with col_btn:
                            st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
                            if st.button("Update Status", key="btn_update_user_status") and selected_user_label:
                                target = next(u for u in manageable if f"{u['email']} ({u['role']})" == selected_user_label)
                                try:
                                    client.update_tenant_user(target["id"], is_active=(new_status == "Active"))
                                    st.success(f"Updated account status for {target['email']}!")
                                    st.rerun()
                                except APIError as exc:
                                    st.error(exc.message)
                except APIError as exc:
                    st.caption(f"Could not load users: {exc.message}")

    st.markdown(
        clean_html(
            """
            <div class="le-card" style="margin-bottom:0.85rem;">
                <div style="font-size:0.9rem; font-weight:700; color:#101B35; margin-bottom:0.35rem;">
                    🏢 Strict Multi-Tenant Data Isolation
                </div>
                <div style="font-size:0.82rem; color:#748094; line-height:1.55;">
                    Every document, clause, analysis payload, and report is strictly scoped to the tenant ID embedded
                    within the authenticated JWT token. Cross-tenant access is blocked at the database and filesystem levels.
                </div>
            </div>

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
            """
        ),
        unsafe_allow_html=True,
    )

render_disclaimer_footer()
