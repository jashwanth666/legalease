"""Shared enterprise SaaS styling, navigation layout, sidebar branding, and active document selector."""

from typing import Any
import streamlit as st

from frontend.utils.api_client import APIError, LegalEaseAPIClient


CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

:root {
    --le-navy: #101B35;
    --le-navy-dark: #0B1325;
    --le-navy-light: #172642;
    --le-blue: #356AE6;
    --le-blue-hover: #2655C4;
    --le-blue-subtle: #EDF3FF;
    --le-bg: #F7F9FC;
    --le-card: #FFFFFF;
    --le-text-primary: #172033;
    --le-text-secondary: #748094;
    --le-text-muted: #94A3B8;
    --le-border: #E6EAF0;
    --le-border-light: #F1F4F9;
    --le-success: #16A36A;
    --le-success-bg: #ECFDF5;
    --le-warning: #E69A32;
    --le-warning-bg: #FFFBEB;
    --le-high: #E87536;
    --le-high-bg: #FFF7ED;
    --le-critical: #DC4545;
    --le-critical-bg: #FEF2F2;
    --le-purple: #8B5CF6;
    --le-purple-bg: #F5F3FF;
    --le-radius-sm: 8px;
    --le-radius-md: 12px;
    --le-radius-lg: 16px;
    --le-shadow-xs: 0 1px 2px rgba(16, 27, 53, 0.04);
    --le-shadow-sm: 0 2px 8px rgba(16, 27, 53, 0.05);
    --le-shadow-md: 0 4px 16px rgba(16, 27, 53, 0.08);
}

/* Global Font & App Reset */
html, body, [class*="css"], .stMarkdown, p, div, span, label, button, input, select {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
}

.stApp {
    background-color: var(--le-bg);
    color: var(--le-text-primary);
}

/* Hide Streamlit Chrome for Clean SaaS Look */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header[data-testid="stHeader"] {
    background: transparent;
    z-index: 1;
}
.stDeployButton { display: none; }

/* Sidebar Premium Deep Navy Styling */
[data-testid="stSidebar"] {
    background-color: var(--le-navy) !important;
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    box-shadow: 2px 0 12px rgba(11, 19, 37, 0.15);
}

[data-testid="stSidebar"] * {
    color: #F8FAFC;
}

[data-testid="stSidebar"] h1, 
[data-testid="stSidebar"] h2, 
[data-testid="stSidebar"] h3 {
    color: #FFFFFF !important;
    font-weight: 700;
}

[data-testid="stSidebar"] hr {
    border-color: rgba(255, 255, 255, 0.1) !important;
}

/* Sidebar Selectbox */
[data-testid="stSidebar"] .stSelectbox label {
    color: #CBD5E1 !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] {
    background-color: #172642 !important;
    border: 1px solid rgba(255, 255, 255, 0.14) !important;
    border-radius: var(--le-radius-sm) !important;
}

[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] * {
    color: #F8FAFC !important;
}

/* Sidebar Navigation Items */
[data-testid="stSidebarNav"] li a {
    border-radius: var(--le-radius-sm);
    padding: 0.5rem 0.75rem !important;
    margin: 0.15rem 0.5rem !important;
    font-weight: 500;
    transition: all 0.2s ease;
}

[data-testid="stSidebarNav"] li a:hover {
    background-color: rgba(255, 255, 255, 0.08) !important;
    color: #FFFFFF !important;
}

[data-testid="stSidebarNav"] li a[aria-current="page"] {
    background-color: rgba(53, 106, 230, 0.22) !important;
    border-left: 3px solid var(--le-blue) !important;
    color: #FFFFFF !important;
    font-weight: 600;
}

/* Premium Page Header Banner */
.le-page-header {
    background: #FFFFFF;
    border: 1px solid var(--le-border);
    border-radius: var(--le-radius-md);
    padding: 1.25rem 1.75rem;
    margin-bottom: 1.5rem;
    box-shadow: var(--le-shadow-xs);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 1rem;
}

.le-header-content {
    flex: 1;
    min-width: 280px;
}

.le-breadcrumbs {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--le-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.35rem;
}

.le-breadcrumbs span.active {
    color: var(--le-blue);
}

.le-page-title {
    margin: 0;
    font-size: 1.6rem;
    font-weight: 800;
    color: var(--le-navy);
    letter-spacing: -0.02em;
    line-height: 1.2;
}

.le-page-subtitle {
    margin: 0.35rem 0 0 0;
    font-size: 0.88rem;
    color: var(--le-text-secondary);
    line-height: 1.45;
}

/* Premium Card Styles */
.le-card {
    background: var(--le-card);
    border: 1px solid var(--le-border);
    border-radius: var(--le-radius-md);
    padding: 1.25rem 1.4rem;
    margin-bottom: 1rem;
    box-shadow: var(--le-shadow-xs);
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.le-card:hover {
    box-shadow: var(--le-shadow-sm);
    border-color: #D3DBE6;
}

/* KPI Stat Cards */
.le-kpi-card {
    background: var(--le-card);
    border: 1px solid var(--le-border);
    border-radius: var(--le-radius-md);
    padding: 1.15rem 1.25rem;
    box-shadow: var(--le-shadow-xs);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
    height: 100%;
}

.le-kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: var(--le-shadow-sm);
}

.le-kpi-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
}

.le-kpi-label {
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--le-text-secondary);
}

.le-kpi-icon-wrap {
    width: 32px;
    height: 32px;
    border-radius: var(--le-radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1rem;
}

.le-kpi-value {
    font-size: 2rem;
    font-weight: 800;
    color: var(--le-text-primary);
    line-height: 1.1;
    letter-spacing: -0.03em;
}

.le-kpi-subtitle {
    font-size: 0.8rem;
    color: var(--le-text-secondary);
    margin-top: 0.4rem;
    display: flex;
    align-items: center;
    gap: 0.35rem;
}

/* Badges */
.le-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.22rem 0.65rem;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    line-height: 1;
}

.le-badge-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
}

.le-badge-no_notable_risk, .le-badge-neutral {
    background: #F1F5F9;
    color: #475569;
    border: 1px solid #E2E8F0;
}
.le-badge-no_notable_risk .le-badge-dot { background: #64748B; }

.le-badge-low, .le-badge-success {
    background: var(--le-success-bg);
    color: #065F46;
    border: 1px solid #A7F3D0;
}
.le-badge-low .le-badge-dot { background: var(--le-success); }

.le-badge-medium, .le-badge-warning {
    background: var(--le-warning-bg);
    color: #92400E;
    border: 1px solid #FDE68A;
}
.le-badge-medium .le-badge-dot { background: var(--le-warning); }

.le-badge-high {
    background: var(--le-high-bg);
    color: #9A3412;
    border: 1px solid #FED7AA;
}
.le-badge-high .le-badge-dot { background: var(--le-high); }

.le-badge-critical {
    background: var(--le-critical-bg);
    color: #991B1B;
    border: 1px solid #FECACA;
}
.le-badge-critical .le-badge-dot { background: var(--le-critical); }

.le-badge-uncertain {
    background: var(--le-purple-bg);
    color: #5B21B6;
    border: 1px solid #DDD6FE;
}
.le-badge-uncertain .le-badge-dot { background: var(--le-purple); }

/* Sidebar Status Cards */
.le-sidebar-brand {
    padding: 0.75rem 0.25rem 1.25rem 0.25rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    margin-bottom: 1.25rem;
}

.le-sidebar-logo-icon {
    width: 38px;
    height: 38px;
    background: linear-gradient(135deg, #356AE6 0%, #172642 100%);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #FFFFFF;
    font-size: 1.25rem;
    box-shadow: 0 4px 10px rgba(53, 106, 230, 0.35);
}

.le-sidebar-title {
    font-size: 1.15rem;
    font-weight: 800;
    color: #FFFFFF;
    letter-spacing: -0.01em;
    line-height: 1.15;
}

.le-sidebar-subtitle {
    font-size: 0.68rem;
    font-weight: 700;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

.le-sidebar-pill {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: var(--le-radius-sm);
    padding: 0.65rem 0.85rem;
    margin-bottom: 1rem;
}

.le-sidebar-pill-title {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #94A3B8;
    margin-bottom: 0.35rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.le-status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 6px;
}

.le-status-dot.online {
    background: #10B981;
    box-shadow: 0 0 8px rgba(16, 185, 129, 0.6);
}

.le-status-dot.offline {
    background: #EF4444;
}

.le-sidebar-user {
    padding: 0.85rem 0.5rem;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    margin-top: 1.5rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.le-user-avatar {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: linear-gradient(135deg, #356AE6, #6366F1);
    color: #FFFFFF;
    font-weight: 700;
    font-size: 0.85rem;
    display: flex;
    align-items: center;
    justify-content: center;
}

.le-user-info {
    flex: 1;
    overflow: hidden;
}

.le-user-name {
    font-size: 0.85rem;
    font-weight: 700;
    color: #FFFFFF;
    line-height: 1.2;
}

.le-user-role {
    font-size: 0.72rem;
    color: #94A3B8;
}

/* Universal Disclaimer Box */
.le-disclaimer-box {
    background: #FFFFFF;
    border: 1px solid var(--le-border);
    border-left: 4px solid var(--le-blue);
    border-radius: var(--le-radius-sm);
    padding: 0.85rem 1.15rem;
    margin-top: 2rem;
    font-size: 0.8rem;
    color: var(--le-text-secondary);
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    box-shadow: var(--le-shadow-xs);
}

.le-disclaimer-box strong {
    color: var(--le-navy);
}

/* Streamlit Tabs Polish */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background-color: transparent;
    border-bottom: 2px solid var(--le-border);
    padding-bottom: 2px;
}

.stTabs [data-baseweb="tab"] {
    border-radius: var(--le-radius-sm) var(--le-radius-sm) 0 0;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 0.88rem;
    color: var(--le-text-secondary);
}

.stTabs [aria-selected="true"] {
    background-color: #FFFFFF !important;
    color: var(--le-blue) !important;
    border-bottom: 2px solid var(--le-blue) !important;
}

/* Buttons */
.stButton button {
    border-radius: var(--le-radius-sm);
    font-weight: 600;
    font-size: 0.88rem;
    padding: 0.45rem 1.15rem;
    transition: all 0.2s ease;
}

.stButton button[kind="primary"] {
    background-color: var(--le-blue);
    border-color: var(--le-blue);
    color: #FFFFFF;
    box-shadow: 0 2px 6px rgba(53, 106, 230, 0.25);
}

.stButton button[kind="primary"]:hover {
    background-color: var(--le-blue-hover);
    border-color: var(--le-blue-hover);
    box-shadow: 0 4px 10px rgba(53, 106, 230, 0.35);
}

.stButton button[kind="secondary"] {
    background-color: #FFFFFF;
    border-color: var(--le-border);
    color: var(--le-text-primary);
}

.stButton button[kind="secondary"]:hover {
    background-color: var(--le-border-light);
    border-color: #CBD5E1;
}

/* Modern Tables */
.le-table-container {
    background: #FFFFFF;
    border: 1px solid var(--le-border);
    border-radius: var(--le-radius-md);
    overflow: hidden;
    box-shadow: var(--le-shadow-xs);
}

/* Section Dividers */
.le-section-header {
    margin: 1.75rem 0 0.85rem 0;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
}

.le-section-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--le-navy);
    letter-spacing: -0.01em;
    margin: 0;
}

.le-section-subtitle {
    font-size: 0.82rem;
    color: var(--le-text-secondary);
    margin: 0.2rem 0 0 0;
}
</style>
"""


def inject_custom_css() -> None:
    """Inject global CSS variables, fonts, and enterprise styling tokens."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def get_api_client() -> LegalEaseAPIClient:
    """Return an API client instance initialized from session state or default."""
    base_url = st.session_state.get("api_base_url")
    return LegalEaseAPIClient(base_url=base_url)


def render_page_header(
    title: str,
    subtitle: str,
    category: str = "Enterprise SaaS",
    active_doc_name: str | None = None,
) -> None:
    """Render a consistent, high-end SaaS breadcrumb banner across all pages."""
    inject_custom_css()

    active_pill = ""
    if active_doc_name:
        active_pill = f"""
        <div style="background:var(--le-blue-subtle); border:1px solid #D1E0FF; border-radius:999px; padding:0.35rem 0.85rem; font-size:0.78rem; font-weight:600; color:var(--le-blue); display:flex; align-items:center; gap:0.4rem;">
            <span>📄</span> {active_doc_name}
        </div>
        """

    st.markdown(
        f"""
        <div class="le-page-header">
            <div class="le-header-content">
                <div class="le-breadcrumbs">
                    <span>LegalEase</span>
                    <span>/</span>
                    <span>{category}</span>
                    <span>/</span>
                    <span class="active">{title}</span>
                </div>
                <h1 class="le-page-title">{title}</h1>
                <p class="le-page-subtitle">{subtitle}</p>
            </div>
            {active_pill}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_disclaimer_footer() -> None:
    """Render universal professional legal disclaimer banner."""
    st.markdown(
        """
        <div class="le-disclaimer-box">
            <span style="font-size:1.1rem; line-height:1;">⚖️</span>
            <div>
                <strong>Legal Information Notice:</strong>
                LegalEase is an AI-assisted document review and risk screening intelligence tool. Its findings and
                comparisons are informational, probabilistic, and do not constitute legal advice. They do not replace
                review by a qualified attorney.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_context(client: LegalEaseAPIClient) -> tuple[dict | None, list[dict], str | None]:
    """Render complete enterprise sidebar: branding, live engine telemetry, document switcher, and user profile."""
    with st.sidebar:
        # 1. Premium Logo & Brand
        st.markdown(
            """
            <div class="le-sidebar-brand">
                <div class="le-sidebar-logo-icon">⚖️</div>
                <div>
                    <div class="le-sidebar-title">LegalEase</div>
                    <div class="le-sidebar-subtitle">Contract Intelligence</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 2. Telemetry & Engine Health Check
        health_data = None
        try:
            health_data = client.health()
            gemini_on = health_data.get("gemini_configured", False)
            ai_label = "Gemini 2.5 Flash" if gemini_on else "Deterministic Fallback"
            dot_class = "online"

            st.markdown(
                f"""
                <div class="le-sidebar-pill">
                    <div class="le-sidebar-pill-title">
                        <span>Platform Engine</span>
                        <span style="font-size:0.7rem; color:#10B981; font-weight:700;">LIVE</span>
                    </div>
                    <div style="font-size:0.82rem; font-weight:600; color:#FFFFFF; display:flex; align-items:center;">
                        <span class="le-status-dot {dot_class}"></span>
                        {ai_label}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        except APIError as exc:
            st.markdown(
                f"""
                <div class="le-sidebar-pill" style="border-color:#EF4444;">
                    <div class="le-sidebar-pill-title">
                        <span>Backend Offline</span>
                        <span style="color:#EF4444;">DISCONNECTED</span>
                    </div>
                    <div style="font-size:0.78rem; color:#FCA5A5;">{exc.message}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            return None, [], None

        # 3. Active Contract Selector
        docs: list[dict] = []
        try:
            docs = client.list_documents()
        except APIError:
            docs = []

        selected_id = st.session_state.get("selected_document_id")

        st.markdown(
            """
            <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:#94A3B8; margin:0.5rem 0 0.25rem 0;">
                Active Contract
            </div>
            """,
            unsafe_allow_html=True,
        )

        if docs:
            options: dict[str, str] = {}
            for d in docs:
                status_short = d.get("processing_status", "uploaded")
                score_str = f" • {d['overall_risk_score']}/100" if d.get("overall_risk_score") is not None else ""
                label = f"{d['filename']} ({status_short}{score_str})"
                options[label] = d["document_id"]

            labels = list(options.keys())
            default_idx = 0
            if selected_id:
                for idx, label in enumerate(labels):
                    if options[label] == selected_id:
                        default_idx = idx
                        break

            chosen_label = st.selectbox(
                "Select Contract",
                labels,
                index=default_idx,
                key="sidebar_active_contract",
                label_visibility="collapsed",
            )
            selected_id = options[chosen_label]
            st.session_state["selected_document_id"] = selected_id
        else:
            st.session_state["selected_document_id"] = None
            selected_id = None
            st.caption("No contracts uploaded yet. Visit Upload Contract to begin.")

        # 4. Enterprise User Profile Section at Bottom
        st.markdown(
            """
            <div class="le-sidebar-user">
                <div class="le-user-avatar">JR</div>
                <div class="le-user-info">
                    <div class="le-user-name">Jashwanth R</div>
                    <div class="le-user-role">Legal Counsel • Enterprise</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return health_data, docs, selected_id
