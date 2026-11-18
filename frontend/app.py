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

    try:
        bs_info = client.get_bootstrap_status()
        is_bootstrapped = bool(bs_info.get("bootstrapped", True))
    except Exception:
        is_bootstrapped = True

    if not is_bootstrapped:
        tab_login, tab_register, tab_bootstrap = st.tabs(["🔐 Sign In", "📝 Create Account", "🚀 System Admin Setup"])
    else:
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
        st.caption("Need a quick test account? Use the Create Account tab to set up an employee workspace.")

    with tab_register:
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        st.info(
            "ℹ️ **Public Workspace Registration:** New accounts are provisioned with standard **Employee** permissions. "
            "A private, isolated workspace is automatically assigned to your account. "
            "To join an existing corporate organization, request an invitation from your tenant administrator."
        )
        reg_name = st.text_input("Full Name", key="reg_name_input", placeholder="Jashwanth R")
        reg_email = st.text_input("Work Email", key="reg_email_input", placeholder="jashwanth@firm.com")
        reg_password = st.text_input(
            "Password (minimum 8 characters)",
            type="password",
            key="reg_pw_input",
            placeholder="••••••••",
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

    if not is_bootstrapped:
        with tab_bootstrap:
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            st.warning(
                "⚙️ **Initial Administrator Setup:** No system administrator has been provisioned yet. "
                "Provide the server's `ADMIN_BOOTSTRAP_SECRET` to initialize the primary administrator account."
            )
            boot_name = st.text_input("Administrator Full Name", key="boot_name_input", placeholder="System Admin")
            boot_email = st.text_input("Administrator Email", key="boot_email_input", placeholder="admin@enterprise.com")
            boot_pw = st.text_input("Password (minimum 8 characters)", type="password", key="boot_pw_input", placeholder="••••••••")
            boot_secret = st.text_input("Bootstrap Secret Key", type="password", key="boot_secret_input", placeholder="Enter ADMIN_BOOTSTRAP_SECRET")
            boot_tenant = st.text_input("Organization Workspace", value="tenant_admin", key="boot_tenant_input")

            if st.button("Initialize Administrator", type="primary", use_container_width=True, key="boot_submit_btn"):
                if not boot_email or not boot_pw or not boot_secret:
                    st.error("Email, password, and bootstrap secret are required.")
                elif len(boot_pw) < 8:
                    st.error("Password must be at least 8 characters long.")
                else:
                    try:
                        client.bootstrap_admin(
                            email=boot_email.strip(),
                            password=boot_pw,
                            full_name=boot_name.strip() or "Administrator",
                            bootstrap_secret=boot_secret.strip(),
                            tenant_id=boot_tenant.strip() or "tenant_admin",
                        )
                        # Auto-login after bootstrap
                        res = client.login(boot_email.strip(), boot_pw)
                        token = res.get("access_token")
                        st.session_state["auth_token"] = token
                        client.set_token(token)
                        me = client.get_me()
                        st.session_state["user"] = me
                        st.success("System administrator initialized! Loading workspace...")
                        st.rerun()
                    except APIError as exc:
                        st.error(exc.message)


# Verify Authentication
client = get_api_client()
token = st.session_state.get("auth_token")

if not token:
    render_auth_view(client)
    st.stop()

# Ensure token and authenticated user account still exist in backend
try:
    st.session_state["user"] = client.get_me()
except APIError as exc:
    # Token expired, invalid, or user account deleted from database
    st.session_state.pop("auth_token", None)
    st.session_state.pop("user", None)
    st.session_state.pop("selected_document_id", None)
    client.set_token(None)
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

