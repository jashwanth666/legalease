"""Shared SaaS styling, sidebar status, and active document selector."""

import streamlit as st

from frontend.utils.api_client import APIError, LegalEaseAPIClient


CUSTOM_CSS = """
<style>
:root {
    --le-navy: #0F2744;
    --le-blue: #1D4ED8;
    --le-bg: #F8FAFC;
    --le-card: #FFFFFF;
    --le-border: #E2E8F0;
    --le-text: #0F172A;
    --le-muted: #475569;
}

.stApp {
    background-color: var(--le-bg);
}

[data-testid="stSidebar"] {
    background-color: #0F2744;
}

[data-testid="stSidebar"] * {
    color: #F8FAFC;
}

[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] * {
    color: #0F172A !important;
}

.le-header-banner {
    background: linear-gradient(135deg, #0F2744 0%, #1E3A8A 100%);
    color: #FFFFFF;
    padding: 1.25rem 1.5rem;
    border-radius: 12px;
    margin-bottom: 1.25rem;
    box-shadow: 0 4px 14px rgba(15, 39, 68, 0.12);
}

.le-header-banner h1 {
    margin: 0;
    font-size: 1.65rem;
    font-weight: 700;
    color: #FFFFFF;
}

.le-header-banner p {
    margin: 0.35rem 0 0 0;
    font-size: 0.92rem;
    color: #DBEAFE;
}

.le-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 1rem 1.15rem;
    margin-bottom: 0.85rem;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
}

.le-kpi-value {
    font-size: 1.85rem;
    font-weight: 700;
    color: #0F2744;
    line-height: 1.15;
}

.le-kpi-label {
    font-size: 0.82rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #64748B;
    margin-bottom: 0.3rem;
}

.le-badge {
    display: inline-block;
    padding: 0.2rem 0.65rem;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}

.le-badge-low { background: #DCFCE7; color: #166534; border: 1px solid #86EFAC; }
.le-badge-medium { background: #FEF9C3; color: #854D0E; border: 1px solid #FDE047; }
.le-badge-high { background: #FFEDD5; color: #9A3412; border: 1px solid #FDBA74; }
.le-badge-critical { background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; }

.le-disclaimer {
    background: #EFF6FF;
    border-left: 4px solid #1D4ED8;
    padding: 0.75rem 1rem;
    border-radius: 6px;
    font-size: 0.84rem;
    color: #1E3A8A;
    margin-top: 1rem;
}
</style>
"""


def inject_custom_css() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def get_api_client() -> LegalEaseAPIClient:
    base_url = st.session_state.get("api_base_url")
    return LegalEaseAPIClient(base_url=base_url)


def render_page_header(title: str, subtitle: str) -> None:
    inject_custom_css()
    st.markdown(
        f"""
        <div class="le-header-banner">
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_disclaimer_footer() -> None:
    st.markdown(
        """
        <div class="le-disclaimer">
            <strong>Disclaimer:</strong> LegalEase is an AI-assisted document review tool. Its findings are
            informational and may be incomplete or inaccurate. It does not provide legal advice or replace
            review by a qualified legal professional.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_context(client: LegalEaseAPIClient) -> tuple[dict | None, list[dict], str | None]:
    """Render sidebar backend status + active contract selector."""
    with st.sidebar:
        st.markdown("### LegalEase Platform")
        st.caption("Contract Intelligence & Risk Screening")

        health_data = None
        try:
            health_data = client.health()
            st.success("Backend Connected")
            if health_data.get("gemini_configured"):
                st.info("AI Engine: Gemini Configured")
            else:
                st.warning("AI Engine: Deterministic Fallback (No Gemini Key)")
        except APIError as exc:
            st.error(f"Backend Offline: {exc.message}")
            return None, [], None

        docs: list[dict] = []
        try:
            docs = client.list_documents()
        except APIError:
            docs = []

        selected_id = st.session_state.get("selected_document_id")
        if docs:
            options = {
                f"{d['document_id']} — {d['filename']} ({d['processing_status']})": d["document_id"]
                for d in docs
            }
            labels = list(options.keys())
            default_idx = 0
            if selected_id:
                for idx, label in enumerate(labels):
                    if options[label] == selected_id:
                        default_idx = idx
                        break
            chosen_label = st.selectbox(
                "Active Contract",
                labels,
                index=default_idx,
                key="sidebar_active_contract",
            )
            selected_id = options[chosen_label]
            st.session_state["selected_document_id"] = selected_id
        else:
            st.session_state["selected_document_id"] = None
            selected_id = None
            st.caption("No contracts uploaded yet.")

        st.divider()
        st.caption("Prototype screening only — not legal advice.")

    return health_data, docs, selected_id

