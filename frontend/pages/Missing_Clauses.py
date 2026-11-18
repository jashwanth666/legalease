"""Page 6: Missing Clauses & Contract Checklist Auditing."""

import html
import pandas as pd
import streamlit as st

from frontend.components.risk_cards import clean_html, render_kpi_card
from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.utils.api_client import APIError


client = get_api_client()
health, docs, selected_id = render_sidebar_context(client)

render_page_header(
    title="Missing Clauses",
    subtitle="Market standard checklist gap analysis: identify missing protections, unaddressed liabilities, and uncertain classifications.",
    category="Checklist Audit",
    active_doc_name=selected_id,
)

if health is None:
    st.error("Backend offline. Please start or connect to the LegalEase API server.")
    st.stop()

if not selected_id:
    st.markdown(
        clean_html(
            """
            <div class="le-card" style="text-align:center; padding:2rem;">
                <div style="font-size:2rem; margin-bottom:0.5rem;">🧩</div>
                <div style="font-size:1.1rem; font-weight:700; color:#101B35;">No Contract Selected</div>
                <div style="font-size:0.84rem; color:#748094; max-width:400px; margin:0.25rem auto 1rem auto;">
                    Please select an active contract from the sidebar to inspect standard checklist coverage.
                </div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )
    st.stop()

try:
    analysis = client.get_analysis(selected_id)
except APIError as exc:
    st.warning(f"Analysis data not yet available: {exc.message}")
    if st.button("Go to Document Analysis to Run Pipeline", type="primary"):
        st.switch_page("pages/Document_Analysis.py")
    st.stop()

missing = analysis.get("missing_clauses") or {}
contract_type = missing.get("contract_type") or analysis.get("detected_contract_type") or "General"
checklist = missing.get("checklist_categories", [])
detected = set(missing.get("detected_categories", []))
missing_items = missing.get("missing_categories", [])
uncertain = missing.get("uncertain_clauses", [])

# Checklist Methodology Notice
st.markdown(
    clean_html(
        """
        <div style="background:#F8FAFC; border:1px solid #E6EAF0; border-left:4px solid #356AE6; border-radius:8px; padding:0.75rem 1rem; margin-bottom:1.25rem; font-size:0.82rem; color:#748094;">
            <strong style="color:#101B35;">Standard Checklist Guidance:</strong>
            A clause category marked as "Not Detected" indicates it was not identified during segmentation and classification.
            Whether the clause is legally mandatory depends on transaction structure, commercial leverage, and governing jurisdiction.
        </div>
        """
    ),
    unsafe_allow_html=True,
)

# KPI Cards: Checklist Coverage
total_expected = len(checklist)
detected_count = max(0, total_expected - len(missing_items))
coverage_pct = int(round((detected_count / total_expected) * 100)) if total_expected > 0 else 100

c1, c2, c3 = st.columns(3)
with c1:
    render_kpi_card(
        label="Detected Contract Archetype",
        value=contract_type,
        subtitle="Determines expected standard checklist",
        accent="#101B35",
        icon="📑",
    )
with c2:
    render_kpi_card(
        label="Standard Checklist Coverage",
        value=f"{coverage_pct}%",
        subtitle=f"{detected_count} of {total_expected} standard categories detected",
        accent="#16A36A" if coverage_pct >= 75 else "#E69A32",
        icon="✓",
    )
with c3:
    render_kpi_card(
        label="Omitted or Uncertain Provisions",
        value=len(missing_items),
        subtitle="Warrants manual drafting review",
        accent="#DC4545" if len(missing_items) > 2 else "#356AE6",
        icon="⚠️",
    )

st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

# Visual Progress Bar
st.markdown(
    clean_html(
        f"""
        <div style="background:#FFFFFF; border:1px solid #E6EAF0; border-radius:12px; padding:1.2rem; margin-bottom:1.5rem;">
            <div style="display:flex; justify-content:space-between; font-size:0.84rem; font-weight:700; color:#101B35; margin-bottom:0.5rem;">
                <span>Standard Clause Coverage Progress</span>
                <span>{detected_count} / {total_expected} Standard Categories</span>
            </div>
            <div style="background:#EDF2F7; height:10px; border-radius:999px; overflow:hidden;">
                <div style="background:{'#16A36A' if coverage_pct >= 75 else '#E69A32'}; width:{coverage_pct}%; height:100%; border-radius:999px;"></div>
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

# Checklist Matrix
st.markdown(
    clean_html(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">Contract Archetype Checklist Matrix</h3>
                <p class="le-section-subtitle">Comprehensive status of all expected clause categories</p>
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

if checklist:
    rows = []
    missing_map = {m["category"]: m for m in missing_items}
    for cat in checklist:
        if cat in missing_map:
            st_val = missing_map[cat]["status"]
            status_disp = "NOT DETECTED" if st_val == "not_detected" else st_val.upper()
            note_disp = missing_map[cat]["explanation"]
        elif cat in detected:
            status_disp = "DETECTED"
            note_disp = "Explicitly extracted and verified in agreement clauses."
        else:
            status_disp = "NOT DETECTED"
            note_disp = "Standard provision not identified in extracted contract body."
        rows.append({"Clause Category": cat, "Detection Status": status_disp, "Checklist Review Notes": note_disp})

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

# Detailed Missing Clause Cards with Why It Matters, Consequences, and Actions
st.markdown(
    clean_html(
        """
        <div class="le-section-header">
            <div>
                <h3 class="le-section-title">Omitted Clause Risk Assessments</h3>
                <p class="le-section-subtitle">In-depth rationale and recommended drafting additions</p>
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

if not missing_items:
    st.markdown(
        clean_html(
            """
            <div class="le-card" style="border-left:4px solid #16A36A; background:#F0FDF4;">
                <div style="font-size:0.95rem; font-weight:700; color:#166534; margin-bottom:0.25rem;">
                    ✓ Comprehensive Coverage Detected
                </div>
                <div style="font-size:0.84rem; color:#14532D;">
                    All standard checklist categories for this contract archetype were identified. No standard protections appear missing.
                </div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )
else:
    for item in missing_items:
        cat_title = item.get("category", "General Protection")
        status_label = item.get("status", "not_detected").replace("_", " ").upper()
        explanation = item.get("explanation", "Standard provision not identified in extracted clauses.")
        relevance = item.get("relevance_note", "Consider adding this clause to prevent unallocated dispute risk.")

        st.markdown(
            clean_html(
                f"""
                <div class="le-card" style="border-left:4px solid #E69A32; margin-bottom:1rem;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem; margin-bottom:0.6rem;">
                        <div style="font-size:1.1rem; font-weight:700; color:#101B35;">
                            {html.escape(cat_title)}
                        </div>
                        <span style="background:#FFFBEB; color:#92400E; border:1px solid #FDE68A; padding:0.2rem 0.6rem; border-radius:999px; font-size:0.75rem; font-weight:700;">
                            {html.escape(status_label)}
                        </span>
                    </div>

                    <div style="font-size:0.86rem; color:#172033; line-height:1.55; margin-bottom:0.65rem;">
                        <strong>Why This Clause Matters:</strong> {html.escape(explanation)}
                    </div>

                    <div style="background:#FFF7ED; border:1px solid #FED7AA; border-radius:8px; padding:0.65rem 0.85rem; font-size:0.82rem; color:#7C2D12;">
                        <strong>Drafting Recommendation:</strong> {html.escape(relevance)}
                    </div>
                </div>
                """
            ),
            unsafe_allow_html=True,
        )

# Uncertain Classifications Section
if uncertain:
    st.markdown(
        clean_html(
            """
            <div class="le-section-header" style="margin-top:1.5rem;">
                <div>
                    <h3 class="le-section-title">Ambiguous Clauses Flagged for Manual Review</h3>
                    <p class="le-section-subtitle">Clauses where classification confidence was marginal</p>
                </div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )
    st.dataframe(pd.DataFrame(uncertain), use_container_width=True, hide_index=True)

render_disclaimer_footer()
