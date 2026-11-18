"""Clause inspection viewer and enterprise side-by-side RAG benchmark comparison components."""

import html
import streamlit as st


def _clean_html(raw_html: str) -> str:
    """Strip leading whitespace on each line so Markdown parser never renders HTML as an indented code block."""
    lines = [line.strip() for line in raw_html.splitlines() if line.strip()]
    return "\n".join(lines)


def _loc_text(item: dict) -> str:
    """Safely format location for PDF or DOCX."""
    if item.get("location_type") == "docx_paragraph" or item.get("page_number") is None:
        pidx = item.get("paragraph_index")
        return f"DOCX Para {pidx}" if pidx else "DOCX Paragraph"
    return f"Page {item.get('page_number')}"


def render_clause_viewer(clauses: list[dict]) -> None:
    """Display modern filterable search bar and interactive cards for extracted legal clauses."""
    if not clauses:
        st.info("No extracted clauses available for this document.")
        return

    categories = sorted({c.get("category", "Other") for c in clauses})

    filter_col1, filter_col2 = st.columns([1, 2])
    with filter_col1:
        chosen_cats = st.multiselect("Filter by Clause Category", categories, default=categories)
    with filter_col2:
        search_q = st.text_input("🔍 Search within Clause Text, Headings, or IDs", "")

    filtered = [
        c
        for c in clauses
        if c.get("category") in chosen_cats
        and (
            not search_q.strip()
            or search_q.lower() in c.get("title", "").lower()
            or search_q.lower() in c.get("original_text", "").lower()
            or search_q.lower() in c.get("clause_id", "").lower()
        )
    ]

    count_html = f"""
    <div style="font-size:0.8rem; font-weight:600; color:#748094; margin:0.5rem 0 1rem 0;">
        Displaying <span style="color:#101B35; font-weight:700;">{len(filtered)}</span> of {len(clauses)} classified clauses
    </div>
    """
    st.markdown(_clean_html(count_html), unsafe_allow_html=True)

    for idx, cl in enumerate(filtered):
        source = cl.get("classification_source", "deterministic_fallback")
        conf = cl.get("confidence")
        conf_txt = f"{int(round(conf * 100))}%" if isinstance(conf, (int, float)) else "N/A"
        loc_txt = _loc_text(cl)
        is_uncertain = cl.get("segmentation_uncertain", False)

        seg_badge = (
            '<span style="background:#FFF7ED; color:#9A3412; border:1px solid #FED7AA; padding:0.15rem 0.5rem; border-radius:999px; font-size:0.72rem; font-weight:600;">⚠️ Uncertain Split</span>'
            if is_uncertain
            else '<span style="background:#ECFDF5; color:#065F46; border:1px solid #A7F3D0; padding:0.15rem 0.5rem; border-radius:999px; font-size:0.72rem; font-weight:600;">✓ Clean Segment</span>'
        )

        header_label = f"{cl.get('clause_id', 'CL')} • {cl.get('title', 'Untitled')} [{cl.get('category')} • {loc_txt}]"

        with st.expander(header_label, expanded=(idx < 2)):
            header_card_html = f"""
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem; background:#F8FAFC; border:1px solid #E6EAF0; border-radius:8px; padding:0.5rem 0.75rem; margin-bottom:0.75rem;">
                <div style="font-size:0.8rem; color:#172033;">
                    <strong>Category:</strong> <span style="color:#356AE6; font-weight:600;">{html.escape(str(cl.get('category', 'Other')))}</span> &bull;
                    <strong>Classification:</strong> <code>{html.escape(source)}</code> (Confidence {conf_txt})
                </div>
                <div>{seg_badge}</div>
            </div>
            """
            st.markdown(_clean_html(header_card_html), unsafe_allow_html=True)

            if cl.get("description"):
                st.markdown(f"**Clause Synopsis:** {cl['description']}")

            loc_card_html = f"""
            <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:#748094; margin-top:0.75rem; margin-bottom:0.25rem;">
                Verbatim Contract Text ({loc_txt})
            </div>
            """
            st.markdown(_clean_html(loc_card_html), unsafe_allow_html=True)
            st.code(cl.get("original_text", ""), language=None)


def render_side_by_side_comparison(comp: dict, idx: int) -> None:
    """Display uploaded contract clause alongside retrieved FAISS benchmark reference."""
    cid = comp.get("clause_id", "")
    title = comp.get("clause_title", cid)
    cat = comp.get("category", "Other")
    loc_txt = _loc_text(comp)
    sim = comp.get("similarity_score")
    sim_txt = f"{sim:.2f}" if isinstance(sim, (int, float)) else "N/A"

    is_insufficient = comp.get("insufficient_evidence", False)
    v_notes = comp.get("verification_notes")
    if is_insufficient or (not comp.get("verified", True) and not v_notes):
        badge_html = '<span style="background:#FEF2F2; color:#991B1B; border:1px solid #FECACA; padding:0.2rem 0.6rem; border-radius:999px; font-size:0.74rem; font-weight:700;">⚠️ Insufficient Evidence</span>'
    elif comp.get("verified", True):
        badge_html = '<span style="background:#ECFDF5; color:#065F46; border:1px solid #A7F3D0; padding:0.2rem 0.6rem; border-radius:999px; font-size:0.74rem; font-weight:700;">🟢 Verified Grounded</span>'
    else:
        badge_html = f'<span style="background:#FFFBEB; color:#92400E; border:1px solid #FDE68A; padding:0.2rem 0.6rem; border-radius:999px; font-size:0.74rem; font-weight:700;" title="{html.escape(v_notes or "")}">🟡 Unverified Citation</span>'

    card_header = f"""
    <div class="le-card" style="border-top:3px solid #356AE6; margin-bottom:1.5rem;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem; margin-bottom:1rem; padding-bottom:0.75rem; border-bottom:1px solid #F1F4F9;">
            <div>
                <span style="background:#101B35; color:#FFFFFF; font-size:0.75rem; font-weight:700; padding:0.2rem 0.55rem; border-radius:6px; letter-spacing:0.04em; margin-right:0.4rem;">
                    {html.escape(str(cid))}
                </span>
                <span style="font-size:1.1rem; font-weight:700; color:#101B35;">
                    {html.escape(str(title))}
                </span>
                <span style="font-size:0.8rem; color:#748094; margin-left:0.4rem;">
                    ({html.escape(str(cat))} &bull; {html.escape(loc_txt)})
                </span>
            </div>
            <div style="display:flex; align-items:center; gap:0.75rem;">
                {badge_html}
                <span style="font-size:0.8rem; font-weight:600; color:#101B35; background:#F8FAFC; border:1px solid #E6EAF0; padding:0.25rem 0.65rem; border-radius:6px;">
                    Semantic Match: <strong>{sim_txt}</strong>
                </span>
            </div>
        </div>
    </div>
    """
    st.markdown(_clean_html(card_header), unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        uploaded_header = f"""
        <div style="font-size:0.78rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:#101B35; margin-bottom:0.35rem; display:flex; align-items:center; gap:0.4rem;">
            <span>📄</span> Uploaded Agreement Clause ({loc_txt})
        </div>
        """
        st.markdown(_clean_html(uploaded_header), unsafe_allow_html=True)
        st.text_area(
            f"Uploaded {cid}",
            value=comp.get("uploaded_clause", ""),
            height=160,
            disabled=True,
            key=f"cmp_up_{cid}_{idx}",
            label_visibility="collapsed",
        )

    with right:
        ref_source = comp.get("reference_source", "standard_template")
        ref_header = f"""
        <div style="font-size:0.78rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:#356AE6; margin-bottom:0.35rem; display:flex; align-items:center; gap:0.4rem;">
            <span>⚖️</span> Reference Benchmark (<code>{html.escape(ref_source)}</code>)
        </div>
        """
        st.markdown(_clean_html(ref_header), unsafe_allow_html=True)
        st.text_area(
            f"Reference {cid}",
            value=comp.get("reference_clause", ""),
            height=160,
            disabled=True,
            key=f"cmp_ref_{cid}_{idx}",
            label_visibility="collapsed",
        )

    # Key Differences, Legal Implications & Recommendations
    diffs = comp.get("differences") or []
    implications = comp.get("potential_implications")
    recommendation = comp.get("recommendation")

    if diffs or implications or recommendation:
        st.markdown(
            _clean_html("""
            <div style="background:#F8FAFC; border:1px solid #E6EAF0; border-radius:10px; padding:1rem; margin-top:1rem;">
            """),
            unsafe_allow_html=True,
        )

        if diffs:
            st.markdown(
                _clean_html("""
                <div style="font-size:0.78rem; font-weight:700; text-transform:uppercase; color:#101B35; margin-bottom:0.3rem;">
                    Key Structural & Linguistic Differences
                </div>
                """),
                unsafe_allow_html=True,
            )
            for d in diffs:
                st.markdown(f"- {d}")

        if implications:
            st.markdown(
                _clean_html(f"""
                <div style="margin-top:0.6rem; font-size:0.84rem; color:#7C2D12; background:#FFF7ED; border:1px solid #FED7AA; border-radius:6px; padding:0.5rem 0.75rem;">
                    <strong>Potential Risk / Implication:</strong> {html.escape(implications)}
                </div>
                """),
                unsafe_allow_html=True,
            )

        if recommendation:
            st.markdown(
                _clean_html(f"""
                <div style="margin-top:0.5rem; font-size:0.84rem; color:#1E40AF; background:#EFF6FF; border:1px solid #BFDBFE; border-radius:6px; padding:0.5rem 0.75rem;">
                    <strong>Suggested Drafting Action:</strong> {html.escape(recommendation)}
                </div>
                """),
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

    notice_html = f"""
    <div style="margin-top:0.5rem; margin-bottom:1.5rem; font-size:0.72rem; color:#94A3B8; font-style:italic;">
        {html.escape(comp.get('illustrative_notice', 'Illustrative reference example only, not a universally applicable legal standard.'))}
    </div>
    """
    st.markdown(_clean_html(notice_html), unsafe_allow_html=True)
