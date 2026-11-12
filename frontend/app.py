"""Main Streamlit application entrypoint registering all 8 LegalEase pages."""

from pathlib import Path
import sys

import streamlit as st


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


st.set_page_config(
    page_title="LegalEase | AI Contract Intelligence",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

pages = [
    st.Page("pages/1_Dashboard.py", title="1. Dashboard", icon="📊", default=True),
    st.Page("pages/2_Upload_Contract.py", title="2. Upload Contract", icon="📤"),
    st.Page("pages/Document_Analysis.py", title="3. Document Analysis", icon="📄"),
    st.Page("pages/3_Risk_Analysis.py", title="4. Risk Assessment", icon="🛡️"),
    st.Page("pages/4_Clause_Comparison.py", title="5. Clause Comparison", icon="⚖️"),
    st.Page("pages/Missing_Clauses.py", title="6. Missing Clauses", icon="🧩"),
    st.Page("pages/5_Reports.py", title="7. Reports", icon="📑"),
    st.Page("pages/Settings.py", title="8. Settings", icon="⚙️"),
]

nav = st.navigation(pages)
nav.run()

