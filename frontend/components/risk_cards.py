"""Reusable KPI and risk-finding cards for Streamlit pages."""

import html
import streamlit as st


RISK_COLORS = {
    "no_notable_risk": "#475569",
    "uncertain": "#7C3AED",
    "low": "#16A34A",
    "medium": "#CA8A04",
    "high": "#EA580C",
    "critical": "#DC2626",
}


def risk_badge_html(level: str) -> str:
    norm = (level or "no_notable_risk").lower()
    if norm not in RISK_COLORS:
        norm = "no_notable_risk"
    label = norm.replace("_", " ").upper()
    return f'<span class="le-badge le-badge-{norm}">{label}</span>'


def format_location_label(item: dict) -> str:
    if item.get("location_type") == "docx_paragraph" or item.get("page_number") is None:
        pidx = item.get("paragraph_index")
        return f"DOCX Para {pidx}" if pidx else "DOCX"
    return f"Page {item.get('page_number')}"


def render_kpi_card(label: str, value: str | int | float, subtitle: str = "", accent: str = "#0F2744") -> None:
    safe_label = html.escape(str(label))
    safe_val = html.escape(str(value))
    safe_sub = html.escape(str(subtitle))
    st.markdown(
        f"""
        <div class="le-card" style="border-top: 4px solid {accent};">
            <div class="le-kpi-label">{safe_label}</div>
            <div class="le-kpi-value" style="color: {accent};">{safe_val}</div>
            <div style="font-size: 0.82rem; color: #64748B; margin-top: 0.25rem;">{safe_sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_risk_finding_card(finding: dict, index: int) -> None:
    level = str(finding.get("risk_level", "no_notable_risk")).lower()
    score = finding.get("risk_score")
    clause_id = finding.get("clause_id", "")
    title = finding.get("risk_title") or finding.get("clause_title") or clause_id
    loc_label = format_location_label(finding)
    verified = finding.get("verified", True)
    finding_type = finding.get("finding_type", "detected_risk")

    badge = risk_badge_html(level)
    score_html = f"{score}/100" if score is not None else "Unscored"
    ver_label = "Verified Evidence" if verified else "Unverified — Review Required"
    ver_color = "#15803D" if verified else "#B91C1C"

    st.markdown(
        f"""
        <div class="le-card" style="border-left: 5px solid {RISK_COLORS.get(level, '#1D4ED8')};">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
                <div>
                    <strong>{html.escape(str(clause_id))}</strong> &mdash;
                    <span style="font-size:1.03rem; font-weight:600; color:#0F2744;">{html.escape(str(title))}</span>
                </div>
                <div>
                    {badge}
                    <span style="margin-left:0.5rem; font-weight:700; color:#0F2744;">{score_html}</span>
                    <span style="margin-left:0.5rem; font-size:0.82rem; color:#475569;">{html.escape(loc_label)}</span>
                </div>
            </div>
            <div style="margin-top:0.45rem; font-size:0.8rem; color:{ver_color}; font-weight:600;">
                {html.escape(ver_label)} &bull; Screening Result: {html.escape(str(finding_type).replace('_', ' ').title())}
            </div>
            <p style="margin:0.55rem 0 0.35rem 0; color:#1E293B;"><strong>Explanation:</strong> {html.escape(str(finding.get('explanation', '')))}</p>
            <p style="margin:0.2rem 0; color:#334155;"><strong>Potential Impact:</strong> {html.escape(str(finding.get('potential_impact', '')))}</p>
            <p style="margin:0.2rem 0 0 0; color:#1E3A8A;"><strong>Suggested Action:</strong> {html.escape(str(finding.get('suggested_action', '')))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander(f"View complete original clause text ({clause_id}, {loc_label})"):
        st.text_area(
            f"Original Clause {clause_id}",
            value=finding.get("original_clause", ""),
            height=130,
            disabled=True,
            key=f"risk_orig_{clause_id}_{index}",
            label_visibility="collapsed",
        )

