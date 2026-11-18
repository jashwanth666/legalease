"""Main Streamlit application entrypoint registering all 8 LegalEase SaaS pages."""

from pathlib import Path
import sys

import streamlit as st


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


st.set_page_config(
    page_title="LegalEase | Enterprise Legal AI",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

"""Main Streamlit application entrypoint registering all 8 LegalEase SaaS pages."""

import html
from pathlib import Path
import sys

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from frontend.components.sidebar import CUSTOM_CSS, get_api_client
from frontend.utils.api_client import APIError, LegalEaseAPIClient


st.set_page_config(
    page_title="LegalEase | Enterprise Legal AI",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def render_auth_view(client: LegalEaseAPIClient) -> None:
    """Render modern enterprise authentication screen for unauthenticated sessions."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    _, center_col, _ = st.columns([1, 2, 1])

    with center_col:
        st.markdown(
            """
            <div style="text-align:center; padding: 2.5rem 1rem 1.5rem 1rem;">
                <div style="font-size: 3rem; margin-bottom: 0.25rem;">⚖️</div>
                <h1 style="font-size: 2.2rem; font-weight: 800; color: #101B35; letter-spacing: -0.02em; margin-bottom: 0.35rem;">
                    LegalEase
                </h1>
                <p style="font-size: 0.95rem; color: #748094; max-width: 440px; margin: 0 auto;">
                    Enterprise AI Contract Intelligence & Continuous Risk Assessment
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        tab_login, tab_register = st.tabs(["🔐 Sign In", "📝 Create Account"])

        with tab_login:
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            login_email = st.text_input("Work Email", key="login_email_input", placeholder="counsel@enterprise.com")
            login_password = st.text_input("Password", type="password", key="login_pw_input", placeholder="••••••••")

            if st.button("Sign In", type="primary", use_container_width=True, key="login_submit_btn"):
                if not login_email or not login_password:
                    st.error("Please provide both email and password.")
                else:
                    try:
                        res = client.login(login_email.strip(), login_password)
                        token = res.get("access_token")
                        st.session_state["auth_token"] = token
                        client.set_token(token)
                        me = client.get_me()
                        st.session_state["user"] = me
                        st.success(f"Authenticated as {me.get('full_name')} ({me.get('role')})")
                        st.rerun()
                    except APIError as exc:
                        st.error(exc.message)

            st.markdown("<hr style='margin:1.5rem 0; opacity:0.15;' />", unsafe_allow_html=True)
            st.caption("Need a quick test account? Use the Create Account tab to set up an admin or reviewer in your tenant.")

        with tab_register:
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            reg_name = st.text_input("Full Name", key="reg_name_input", placeholder="Jashwanth R")
            reg_email = st.text_input("Work Email", key="reg_email_input", placeholder="jashwanth@firm.com")
            reg_password = st.text_input(
                "Password (minimum 8 characters)",
                type="password",
                key="reg_pw_input",
                placeholder="••••••••",
            )

            reg_role = st.selectbox(
                "Role",
                options=["legal_reviewer", "admin", "employee"],
                format_func=lambda r: {
                    "admin": "Admin (Full Organization Management)",
                    "legal_reviewer": "Legal Reviewer (Contract Risk Assessment & Audit)",
                    "employee": "Employee (Document Ingestion & Read-Only)",
                }.get(r, r),
                key="reg_role_input",
            )

            reg_tenant = st.text_input(
                "Organization / Tenant ID",
                value="default_tenant",
                key="reg_tenant_input",
                help="Multi-tenant isolation scopes all contracts, vector stores, and reports to this organization ID.",
            )

            if st.button("Create Account & Workspace", type="primary", use_container_width=True, key="reg_submit_btn"):
                if not reg_name.strip() or not reg_email.strip() or not reg_password:
                    st.error("All fields are required.")
                elif len(reg_password) < 8:
                    st.error("Password must be at least 8 characters long.")
                else:
                    try:
                        client.register(
                            email=reg_email.strip(),
                            password=reg_password,
                            full_name=reg_name.strip(),
                            role=reg_role,
                            tenant_id=reg_tenant.strip() or "default_tenant",
                        )
                        # Auto-login after registration
                        res = client.login(reg_email.strip(), reg_password)
                        token = res.get("access_token")
                        st.session_state["auth_token"] = token
                        client.set_token(token)
                        me = client.get_me()
                        st.session_state["user"] = me
                        st.success("Account created successfully! Loading workspace...")
                        st.rerun()
                    except APIError as exc:
                        st.error(exc.message)


# Verify Authentication
client = get_api_client()
token = st.session_state.get("auth_token")

if not token:
    render_auth_view(client)
    st.stop()

# Ensure token is still valid
try:
    if "user" not in st.session_state:
        st.session_state["user"] = client.get_me()
except APIError as exc:
    # Token expired or invalid
    st.session_state.pop("auth_token", None)
    st.session_state.pop("user", None)
    render_auth_view(client)
    st.stop()

pages = [
    st.Page("pages/1_Dashboard.py", title="Dashboard", icon="📊", default=True),
    st.Page("pages/2_Upload_Contract.py", title="Upload Contract", icon="📤"),
    st.Page("pages/Document_Analysis.py", title="Document Analysis", icon="📄"),
    st.Page("pages/3_Risk_Analysis.py", title="Risk Assessment", icon="🛡️"),
    st.Page("pages/4_Clause_Comparison.py", title="Clause Comparison", icon="⚖️"),
    st.Page("pages/Missing_Clauses.py", title="Missing Clauses", icon="🧩"),
    st.Page("pages/5_Reports.py", title="Reports", icon="📑"),
    st.Page("pages/Settings.py", title="Settings", icon="⚙️"),
]

nav = st.navigation(pages)
nav.run()

