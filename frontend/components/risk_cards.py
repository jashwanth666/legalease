"""Reusable SaaS KPI stat cards, risk badges, overall risk score gauges, and finding components."""

import html
import streamlit as st


RISK_COLORS = {
    "no_notable_risk": "#748094",
    "uncertain": "#8B5CF6",
    "low": "#16A36A",
    "medium": "#E69A32",
    "high": "#E87536",
    "critical": "#DC4545",
}

RISK_BG_COLORS = {
    "no_notable_risk": "#F1F5F9",
    "uncertain": "#F5F3FF",
    "low": "#ECFDF5",
    "medium": "#FFFBEB",
    "high": "#FFF7ED",
    "critical": "#FEF2F2",
}


def risk_badge_html(level: str) -> str:
    """Return an accessible, color-coded HTML status badge with dot indicator."""
    norm = (level or "no_notable_risk").lower()
    if norm not in RISK_COLORS:
        norm = "no_notable_risk"
    label = norm.replace("_", " ").upper()
    return f"""
    <span class="le-badge le-badge-{norm}">
        <span class="le-badge-dot"></span>
        {label}
    </span>
    """


def format_location_label(item: dict) -> str:
    """Format PDF page numbers or DOCX paragraph references safely."""
    if item.get("location_type") == "docx_paragraph" or item.get("page_number") is None:
        pidx = item.get("paragraph_index")
        return f"DOCX Para {pidx}" if pidx else "DOCX Paragraph"
    return f"Page {item.get('page_number')}"


def render_kpi_card(
    label: str,
    value: str | int | float,
    subtitle: str = "",
    accent: str = "#356AE6",
    icon: str = "📊",
    trend: str = "",
) -> None:
    """Render a polished SaaS KPI stat card with top accent bar, icon, and large metric."""
    safe_label = html.escape(str(label))
    safe_val = html.escape(str(value))
    safe_sub = html.escape(str(subtitle))
    trend_html = f"<span style='color:{accent}; font-weight:700;'>{html.escape(trend)}</span> " if trend else ""

    st.markdown(
        f"""
        <div class="le-kpi-card" style="border-top: 3px solid {accent};">
            <div class="le-kpi-header">
                <span class="le-kpi-label">{safe_label}</span>
                <div class="le-kpi-icon-wrap" style="background:{accent}15; color:{accent};">
                    {icon}
                </div>
            </div>
            <div class="le-kpi-value">{safe_val}</div>
            <div class="le-kpi-subtitle">
                {trend_html}{safe_sub}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_risk_score_gauge(
    score: float | int | None,
    level: str,
    limitations: str | None = None,
    mode: str | None = None,
) -> None:
    """Render a prominent hero risk score gauge with severity bands and progress meter."""
    norm_lvl = (level or "no_notable_risk").lower()
    color = RISK_COLORS.get(norm_lvl, "#748094")
    num_score = float(score) if score is not None else 0.0
    val_disp = f"{num_score:.1f}" if score is not None else "N/A"
    pct_fill = min(100.0, max(0.0, num_score))

    badge = risk_badge_html(norm_lvl)
    mode_text = f"Analyzed via: <strong>{html.escape(mode)}</strong>" if mode else ""
    lim_text = html.escape(limitations or "Transparent risk screening: 40% severity, 30% unfavorable wording, 20% missing protections, 10% ambiguity.")

    st.markdown(
        f"""
        <div class="le-card" style="padding:1.5rem; border:1px solid #E6EAF0; border-radius:14px; background:linear-gradient(180deg, #FFFFFF 0%, #FBFDFF 100%);">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:1rem;">
                <div>
                    <div style="font-size:0.78rem; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:#748094; margin-bottom:0.25rem;">
                        Composite Contract Risk Rating
                    </div>
                    <div style="display:flex; align-items:baseline; gap:0.75rem;">
                        <span style="font-size:2.8rem; font-weight:800; color:{color}; line-height:1; letter-spacing:-0.03em;">
                            {val_disp}
                        </span>
                        <span style="font-size:1.1rem; font-weight:600; color:#748094;">/ 100</span>
                        <div style="margin-left:0.5rem;">{badge}</div>
                    </div>
                </div>
                <div style="text-align:right; font-size:0.8rem; color:#748094;">
                    <div>{mode_text}</div>
                    <div style="font-size:0.74rem; color:#94A3B8; margin-top:0.25rem;">Scale: 0 (Safe) to 100 (Critical Risk)</div>
                </div>
            </div>

            <!-- Visual Gradient Progress Bar -->
            <div style="margin-top:1.25rem; background:#EDF2F7; height:12px; border-radius:999px; overflow:hidden; position:relative;">
                <div style="background:{color}; width:{pct_fill}%; height:100%; border-radius:999px; transition:width 0.6s ease;"></div>
            </div>

            <!-- Severity Band Markers -->
            <div style="display:flex; justify-content:space-between; margin-top:0.5rem; font-size:0.72rem; font-weight:600; color:#94A3B8;">
                <span style="color:#16A36A;">Low (0–29)</span>
                <span style="color:#E69A32;">Medium (30–59)</span>
                <span style="color:#E87536;">High (60–79)</span>
                <span style="color:#DC4545;">Critical (80–100)</span>
            </div>

            <div style="margin-top:1rem; padding-top:0.85rem; border-top:1px solid #F1F4F9; font-size:0.78rem; color:#748094;">
                <span style="font-weight:600; color:#172033;">Scoring Framework:</span> {lim_text}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_risk_finding_card(finding: dict, index: int) -> None:
    """Render an individual risk finding in an enterprise SaaS card."""
    level = str(finding.get("risk_level", "no_notable_risk")).lower()
    color = RISK_COLORS.get(level, "#748094")
    score = finding.get("risk_score")
    clause_id = finding.get("clause_id", "")
    title = finding.get("risk_title") or finding.get("clause_title") or clause_id
    loc_label = format_location_label(finding)
    verified = finding.get("verified", True)
    finding_type = finding.get("finding_type", "detected_risk")

    badge = risk_badge_html(level)
    score_html = f"<span style='font-size:0.85rem; font-weight:700; color:{color};'>{score}/100</span>" if score is not None else "<span style='font-size:0.78rem; color:#748094;'>Unscored Routine Clause</span>"

    if verified:
        ver_pill = '<span style="background:#ECFDF5; color:#065F46; border:1px solid #A7F3D0; padding:0.15rem 0.5rem; border-radius:999px; font-size:0.72rem; font-weight:600;">✓ Verified Evidence</span>'
    else:
        ver_pill = '<span style="background:#FEF2F2; color:#991B1B; border:1px solid #FECACA; padding:0.15rem 0.5rem; border-radius:999px; font-size:0.72rem; font-weight:600;">⚠️ Unverified &bull; Review Required</span>'

    st.markdown(
        f"""
        <div class="le-card" style="border-left: 4px solid {color}; margin-bottom: 1.15rem;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem; margin-bottom:0.75rem;">
                <div style="display:flex; align-items:center; gap:0.6rem; flex-wrap:wrap;">
                    <span style="background:#101B35; color:#FFFFFF; font-size:0.75rem; font-weight:700; padding:0.2rem 0.55rem; border-radius:6px; letter-spacing:0.04em;">
                        {html.escape(str(clause_id))}
                    </span>
                    <span style="font-size:1.05rem; font-weight:700; color:#101B35;">
                        {html.escape(str(title))}
                    </span>
                </div>
                <div style="display:flex; align-items:center; gap:0.65rem; flex-wrap:wrap;">
                    {badge}
                    {score_html}
                    <span style="font-size:0.78rem; color:#748094; font-weight:600; background:#F1F4F9; padding:0.2rem 0.55rem; border-radius:6px;">
                        📍 {html.escape(loc_label)}
                    </span>
                    {ver_pill}
                </div>
            </div>

            <!-- Finding Type & Summary -->
            <div style="font-size:0.85rem; color:#172033; line-height:1.55; margin-bottom:0.75rem;">
                <strong style="color:#101B35;">Explanation:</strong> {html.escape(str(finding.get('explanation', '')))}
            </div>

            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:0.75rem; margin-top:0.65rem;">
                <div style="background:#FFF9F5; border:1px solid #FFE4D6; border-radius:8px; padding:0.65rem 0.85rem;">
                    <div style="font-size:0.74rem; font-weight:700; text-transform:uppercase; color:#C2410C; margin-bottom:0.2rem;">
                        ⚡ Potential Legal & Business Impact
                    </div>
                    <div style="font-size:0.82rem; color:#7C2D12;">
                        {html.escape(str(finding.get('potential_impact', 'Not specified.')))}
                    </div>
                </div>

                <div style="background:#F0F6FF; border:1px solid #D6E4FF; border-radius:8px; padding:0.65rem 0.85rem;">
                    <div style="font-size:0.74rem; font-weight:700; text-transform:uppercase; color:#2563EB; margin-bottom:0.2rem;">
                        💡 Recommended Counsel Action
                    </div>
                    <div style="font-size:0.82rem; color:#1E40AF;">
                        {html.escape(str(finding.get('suggested_action', 'Review with legal counsel.')))}
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander(f"Inspect verbatim contract clause text ({clause_id} • {loc_label})"):
        st.text_area(
            f"Original Clause {clause_id}",
            value=finding.get("original_clause", ""),
            height=120,
            disabled=True,
            key=f"risk_orig_{clause_id}_{index}",
            label_visibility="collapsed",
        )
