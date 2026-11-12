"""Page 5: RAG Reference Template Clause Comparison."""

import streamlit as st

from frontend.components.clause_viewer import render_side_by_side_comparison
from frontend.components.sidebar import (
    get_api_client,
    render_disclaimer_footer,
    render_page_header,
    render_sidebar_context,
)
from frontend.utils.api_client import APIError


render_page_header(
    "Clause Comparison (RAG)",
    "Side-by-side comparison between uploaded contract clauses and FAISS-retrieved illustrative reference templates.",
)

client = get_api_client()
health, _, selected_id = render_sidebar_context(client)

if health is None:
    st.stop()

if not selected_id:
    st.info("Select or upload a contract first.")
    st.stop()

try:
    compare_data = client.get_comparisons(selected_id)
except APIError as exc:
    st.warning(exc.message)
    st.stop()

st.info(compare_data.get("illustrative_notice"))
st.caption(
    f"Contract: **{compare_data.get('filename')}** • "
    f"Detected Type: **{compare_data.get('detected_contract_type')}** • "
    f"Compared Clauses: **{compare_data.get('count', 0)}**"
)

comparisons = compare_data.get("comparisons", [])
if not comparisons:
    st.info("No matching reference clause comparisons were found for this contract.")
else:
    categories = sorted({c.get("category", "Other") for c in comparisons})
    selected_cats = st.multiselect("Filter by Category", categories, default=categories)
    filtered = [c for c in comparisons if c.get("category") in selected_cats]
    for idx, comp in enumerate(filtered):
        render_side_by_side_comparison(comp, idx)

render_disclaimer_footer()

