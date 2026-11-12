"""Clause inspection and side-by-side reference comparison components."""

import html
import streamlit as st


def render_clause_viewer(clauses: list[dict]) -> None:
    """Display filterable table and expandable full original text for extracted clauses."""
    if not clauses:
        st.info("No extracted clauses available for this document.")
        return

    categories = sorted({c.get("category", "Other") for c in clauses})
    col1, col2 = st.columns([1, 2])
    with col1:
        chosen_cats = st.multiselect("Filter by Category", categories, default=categories)
    with col2:
        search_q = st.text_input("Search Clause Text or Title", "")

    filtered = [
        c
        for c in clauses
        if c.get("category") in chosen_cats
        and (
            not search_q.strip()
            or search_q.lower() in c.get("title", "").lower()
            or search_q.lower() in c.get("original_text", "").lower()
        )
    ]

    st.caption(f"Showing {len(filtered)} of {len(clauses)} extracted clauses")
    for idx, cl in enumerate(filtered):
        source = cl.get("classification_source", "deterministic_fallback")
        conf = cl.get("confidence")
        conf_txt = f"{int(round(conf * 100))}%" if isinstance(conf, (int, float)) else "N/A"
        header = (
            f"{cl.get('clause_id')} | {cl.get('title')} "
            f"[{cl.get('category')} • Page {cl.get('page_number')} • Confidence {conf_txt}]"
        )
        with st.expander(header, expanded=(idx < 2)):
            st.markdown(f"**Classification Source:** `{source}`")
            if cl.get("description"):
                st.markdown(f"**Summary:** {cl['description']}")
            st.markdown("**Complete Original Clause Text:**")
            st.code(cl.get("original_text", ""), language=None)


def render_side_by_side_comparison(comp: dict, idx: int) -> None:
    """Display uploaded contract clause next to retrieved illustrative reference clause."""
    cid = comp.get("clause_id", "")
    title = comp.get("clause_title", cid)
    cat = comp.get("category", "Other")
    page_no = comp.get("page_number", 1)
    sim = comp.get("similarity_score")
    sim_txt = f"{sim:.2f}" if isinstance(sim, (int, float)) else "N/A"
    verified_txt = "Verified" if comp.get("verified", True) else "Unverified"

    st.markdown(
        f"""
        <div class="le-card">
            <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:0.5rem;">
                <div><strong>{html.escape(str(cid))}</strong> &mdash; {html.escape(str(title))} ({html.escape(str(cat))}, Page {page_no})</div>
                <div style="font-size:0.83rem; color:#475569;">
                    Reference: <strong>{html.escape(str(comp.get('reference_source', '')))}</strong>
                    &bull; Similarity: <strong>{sim_txt}</strong> &bull; {verified_txt}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns(2)
    with left:
        st.markdown("**Uploaded Contract Clause**")
        st.text_area(
            f"Uploaded {cid}",
            value=comp.get("uploaded_clause", ""),
            height=170,
            disabled=True,
            key=f"cmp_up_{cid}_{idx}",
            label_visibility="collapsed",
        )
    with right:
        st.markdown(
            f"**Illustrative Reference Clause** (`{comp.get('reference_source', 'reference')}`)"
        )
        st.text_area(
            f"Reference {cid}",
            value=comp.get("reference_clause", ""),
            height=170,
            disabled=True,
            key=f"cmp_ref_{cid}_{idx}",
            label_visibility="collapsed",
        )

    diffs = comp.get("differences") or []
    if diffs:
        st.markdown("**Key Differences Observed:**")
        for diff in diffs:
            st.markdown(f"- {diff}")
    if comp.get("potential_implications"):
        st.markdown(f"**Potential Implications:** {comp['potential_implications']}")
    if comp.get("recommendation"):
        st.markdown(f"**Suggested Review Point:** {comp['recommendation']}")
    st.caption(
        comp.get(
            "illustrative_notice",
            "Illustrative reference example only, not a universally applicable legal standard.",
        )
    )
    st.divider()

