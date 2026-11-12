"""Page 6: Missing & Uncertain Clause Category Detection."""

import pandas as pd
import streamlit as st

from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.utils.api_client import APIError


render_page_header(
    "Missing Clauses",
    "Expected clause-category checklist comparison and uncertain classification review.",
)

client = get_api_client()
health, _, selected_id = render_sidebar_context(client)

if health is None:
    st.stop()

if not selected_id:
    st.info("Select or upload a contract first.")
    st.stop()

try:
    analysis = client.get_analysis(selected_id)
except APIError as exc:
    st.warning(exc.message)
    st.stop()

missing = analysis.get("missing_clauses") or {}
contract_type = missing.get("contract_type") or analysis.get("detected_contract_type") or "General"
checklist = missing.get("checklist_categories", [])
detected = set(missing.get("detected_categories", []))
missing_items = missing.get("missing_categories", [])
uncertain = missing.get("uncertain_clauses", [])

st.info(
    "A category marked as not detected is NOT automatically legally mandatory. "
    "Its relevance depends on the deal structure, jurisdiction, and business circumstances."
)

c1, c2, c3 = st.columns(3)
c1.metric("Detected Contract Type", contract_type)
c2.metric("Checklist Coverage", f"{max(0, len(checklist) - len(missing_items))} / {len(checklist)}")
c3.metric("Missing / Uncertain Items", len(missing_items))

st.subheader("Checklist Coverage Summary")
if checklist:
    rows = []
    missing_map = {m["category"]: m for m in missing_items}
    for cat in checklist:
        if cat in missing_map:
            status = missing_map[cat]["status"]
            note = missing_map[cat]["explanation"]
        elif cat in detected:
            status = "detected"
            note = "Detected in extracted contract clauses."
        else:
            status = "not_detected"
            note = "Not identified."
        rows.append({"Category": cat, "Status": status, "Notes": note})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.subheader("Detailed Missing & Uncertain Categories")
if not missing_items:
    st.success("All expected checklist categories for this contract type were detected.")
else:
    for item in missing_items:
        status_label = item.get("status", "not_detected").replace("_", " ").title()
        st.markdown(
            f"""
            <div class="le-card" style="border-left: 4px solid #CA8A04;">
                <strong>{item.get('category')}</strong>
                <span style="margin-left:0.5rem; font-size:0.82rem; color:#854D0E;">[{status_label}]</span>
                <p style="margin:0.4rem 0 0.2rem 0; color:#1E293B;">{item.get('explanation')}</p>
                <p style="margin:0; font-size:0.83rem; color:#475569;">{item.get('relevance_note', '')}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

if uncertain:
    st.subheader("Clauses Flagged for Manual Review (Low Classification Confidence)")
    st.dataframe(pd.DataFrame(uncertain), use_container_width=True, hide_index=True)

render_disclaimer_footer()

