"""Reusable KPI and risk-finding cards for Streamlit pages."""

import html
import streamlit as st


RISK_COLORS = {
    "low": "#16A34A",
    "medium": "#CA8A04",
    "high": "#EA580C",
    "critical": "#DC2626",
}


def risk_badge_html(level: str) -> str:
    norm = (level or "low").lower()
    if norm not in RISK_COLORS:
        norm = "low"
    return f'<span class="le-badge le-badge-{norm}">{norm.upper()}</span>'


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
    level = str(finding.get("risk_level", "low")).lower()
    score = finding.get("risk_score", 0)
    clause_id = finding.get("clause_id", "")
    title = finding.get("risk_title") or finding.get("clause_title") or clause_id
    page_no = finding.get("page_number", 1)
    verified = finding.get("verified", True)
    finding_type = finding.get("finding_type", "detected_risk")

    badge = risk_badge_html(level)
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
                    <span style="margin-left:0.5rem; font-weight:700; color:#0F2744;">{score}/100</span>
                    <span style="margin-left:0.5rem; font-size:0.82rem; color:#475569;">Page {page_no}</span>
                </div>
            </div>
            <div style="margin-top:0.45rem; font-size:0.8rem; color:{ver_color}; font-weight:600;">
                {html.escape(ver_label)} &bull; Type: {html.escape(str(finding_type).replace('_', ' ').title())}
            </div>
            <p style="margin:0.55rem 0 0.35rem 0; color:#1E293B;"><strong>Explanation:</strong> {html.escape(str(finding.get('explanation', '')))}</p>
            <p style="margin:0.2rem 0; color:#334155;"><strong>Potential Impact:</strong> {html.escape(str(finding.get('potential_impact', '')))}</p>
            <p style="margin:0.2rem 0 0 0; color:#1E3A8A;"><strong>Suggested Action:</strong> {html.escape(str(finding.get('suggested_action', '')))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander(f"View complete original clause text ({clause_id}, Page {page_no})"):
        st.text_area(
            f"Original Clause {clause_id}",
            value=finding.get("original_clause", ""),
            height=130,
            disabled=True,
            key=f"risk_orig_{clause_id}_{index}",
            label_visibility="collapsed",
        )

