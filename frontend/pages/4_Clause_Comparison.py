"""Page 5: Semantic Benchmark Clause Comparison (FAISS Vector RAG)."""

import html
import streamlit as st

from frontend.components.clause_viewer import render_side_by_side_comparison
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
    title="Clause Comparison",
    subtitle="Semantic alignment benchmarking: uploaded contract provisions compared against FAISS standard reference templates.",
    category="Benchmark RAG",
    active_doc_name=selected_id,
)

if health is None:
    st.error("Backend offline. Please start or connect to the LegalEase API server.")
    st.stop()

if not selected_id:
    st.markdown(
        """
        <div class="le-card" style="text-align:center; padding:2rem;">
            <div style="font-size:2rem; margin-bottom:0.5rem;">⚖️</div>
            <div style="font-size:1.1rem; font-weight:700; color:#101B35;">No Contract Selected</div>
            <div style="font-size:0.84rem; color:#748094; max-width:400px; margin:0.25rem auto 1rem auto;">
                Please select a contract from the sidebar to inspect its benchmark clause comparisons.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

try:
    compare_data = client.get_comparisons(selected_id)
except APIError as exc:
    st.warning(f"Comparison data unavailable: {exc.message}")
    if st.button("Go to Document Analysis to Run Pipeline", type="primary"):
        st.switch_page("pages/Document_Analysis.py")
    st.stop()

# Benchmark Context & Notice Bar
st.markdown(
    f"""
    <div class="le-card" style="border-left:4px solid #356AE6; background:#F8FAFC;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
            <div>
                <span style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:#356AE6;">Benchmark Comparison Telemetry</span>
                <div style="font-size:1.1rem; font-weight:700; color:#101B35;">{html.escape(compare_data.get('filename', 'Contract'))}</div>
            </div>
            <div style="font-size:0.82rem; color:#748094;">
                Detected Type: <strong style="color:#101B35;">{html.escape(compare_data.get('detected_contract_type', 'General'))}</strong> &bull;
                Compared Clauses: <strong style="color:#101B35;">{compare_data.get('count', 0)}</strong>
            </div>
        </div>
        <div style="margin-top:0.5rem; font-size:0.8rem; color:#748094; line-height:1.45;">
            {html.escape(compare_data.get('illustrative_notice', 'Illustrative reference templates provide market comparison points, not mandatory drafting standards.'))}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

comparisons = compare_data.get("comparisons", [])
if not comparisons:
    st.markdown(
        """
        <div class="le-card" style="text-align:center; padding:2rem;">
            <div style="font-size:1.8rem; margin-bottom:0.5rem;">🔍</div>
            <div style="font-size:1rem; font-weight:700; color:#101B35;">No Comparative Benchmarks Found</div>
            <div style="font-size:0.82rem; color:#748094; max-width:420px; margin:0.25rem auto 0 auto;">
                The FAISS vector retriever found no relevant reference clauses matching the categories in this document.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    categories = sorted({c.get("category", "Other") for c in comparisons})
    filter_col1, filter_col2 = st.columns([1, 2])
    with filter_col1:
        selected_cats = st.multiselect("Filter by Clause Category", categories, default=categories)
    with filter_col2:
        search_q = st.text_input("Filter Comparison Text or Keywords", "")

    filtered = [
        c for c in comparisons
        if c.get("category") in selected_cats
        and (
            not search_q.strip()
            or search_q.lower() in c.get("clause_title", "").lower()
            or search_q.lower() in c.get("uploaded_clause", "").lower()
            or search_q.lower() in c.get("reference_clause", "").lower()
        )
    ]

    st.markdown(
        f"""
        <div style="font-size:0.8rem; font-weight:600; color:#748094; margin:0.5rem 0 1.25rem 0;">
            Displaying <strong style="color:#101B35;">{len(filtered)}</strong> of {len(comparisons)} comparative clauses
        </div>
        """,
        unsafe_allow_html=True,
    )

    for idx, comp in enumerate(filtered):
        render_side_by_side_comparison(comp, idx)

render_disclaimer_footer()
