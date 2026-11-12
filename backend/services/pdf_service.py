"""ReportLab PDF report generation service for LegalEase."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.config import LEGAL_DISCLAIMER


NAVY = colors.HexColor("#0F2744")
BLUE = colors.HexColor("#1D4ED8")
LIGHT_BG = colors.HexColor("#F1F5F9")
BORDER = colors.HexColor("#CBD5E1")
TEXT_DARK = colors.HexColor("#0F172A")
TEXT_MUTED = colors.HexColor("#475569")

RISK_COLORS = {
    "low": colors.HexColor("#16A34A"),
    "medium": colors.HexColor("#CA8A04"),
    "high": colors.HexColor("#EA580C"),
    "critical": colors.HexColor("#DC2626"),
}


def _safe(value: Any) -> str:
    return escape(str(value or "")).replace("\n", "<br/>")


def _draw_header_footer(canvas, doc, document_id: str) -> None:
    canvas.saveState()
    width, height = LETTER

    # Header bar
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.6)
    canvas.line(0.65 * inch, height - 0.55 * inch, width - 0.65 * inch, height - 0.55 * inch)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(NAVY)
    canvas.drawString(0.65 * inch, height - 0.45 * inch, "LegalEase | Contract Intelligence & Risk Report")
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawRightString(width - 0.65 * inch, height - 0.45 * inch, f"Document ID: {document_id}")

    # Footer
    canvas.line(0.65 * inch, 0.55 * inch, width - 0.65 * inch, 0.55 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawString(
        0.65 * inch,
        0.38 * inch,
        "Informational screening output only — not legal advice.",
    )
    canvas.drawRightString(width - 0.65 * inch, 0.38 * inch, f"Page {doc.page}")
    canvas.restoreState()


def generate_analysis_pdf(
    output_path: Path,
    document_meta: dict[str, Any],
    overview: dict[str, Any],
    executive_summary: str,
    clauses: list[dict[str, Any]],
    risk_results: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    missing_clauses: dict[str, Any],
) -> Path:
    """Build a structured, multi-section LegalEase PDF report using ReportLab."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc_id = document_meta.get("document_id", "UNKNOWN")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "LegalTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        textColor=NAVY,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "LegalSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=TEXT_MUTED,
        spaceAfter=14,
    )
    section_style = ParagraphStyle(
        "LegalSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=NAVY,
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "LegalBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=TEXT_DARK,
        spaceAfter=6,
    )
    small_style = ParagraphStyle(
        "LegalSmall",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=TEXT_MUTED,
        spaceAfter=4,
    )

    story: list[Any] = []

    # 1. LegalEase Branding
    story.append(Paragraph("LegalEase Contract Risk &amp; Intelligence Report", title_style))
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(
        Paragraph(
            f"Generated {generated_at} &nbsp;|&nbsp; Prototype Screening Report",
            subtitle_style,
        )
    )

    # 2. Document Details
    story.append(Paragraph("1. Document Details", section_style))
    details_rows = [
        ["Document ID", str(doc_id), "Filename", str(document_meta.get("filename", ""))],
        [
            "File Type",
            str(document_meta.get("file_type", "")).upper(),
            "Pages",
            str(document_meta.get("page_count", 0)),
        ],
        [
            "Contract Type",
            str(document_meta.get("detected_contract_type") or missing_clauses.get("contract_type", "General")),
            "Analysis Mode",
            str(document_meta.get("analysis_mode", "deterministic_fallback")),
        ],
    ]
    details_table = Table(details_rows, colWidths=[1.2 * inch, 2.2 * inch, 1.2 * inch, 2.4 * inch])
    details_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LIGHT_BG),
                ("BACKGROUND", (2, 0), (2, -1), LIGHT_BG),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(details_table)
    story.append(Spacer(1, 8))

    # 3. Overall Risk Overview & 4. Risk Score Distribution
    story.append(Paragraph("2. Overall Risk Overview &amp; Distribution", section_style))
    overall_score = overview.get("overall_risk_score", 0.0)
    overall_level = str(overview.get("overall_risk_level", "low")).upper()
    overview_rows = [
        ["Overall Illustrative Risk Score", "Overall Risk Level", "Total Clauses"],
        [f"{overall_score} / 100", overall_level, str(overview.get("total_clauses", len(clauses)))],
    ]
    overview_table = Table(overview_rows, colWidths=[2.4 * inch, 2.3 * inch, 2.3 * inch])
    overview_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(overview_table)
    story.append(Spacer(1, 6))

    dist_rows = [
        ["Risk Level", "Score Range", "Clause Count"],
        ["Low", "0 – 29", str(overview.get("low_count", 0))],
        ["Medium", "30 – 59", str(overview.get("medium_count", 0))],
        ["High", "60 – 79", str(overview.get("high_count", 0))],
        ["Critical", "80 – 100", str(overview.get("critical_count", 0))],
    ]
    dist_table = Table(dist_rows, colWidths=[2.4 * inch, 2.3 * inch, 2.3 * inch])
    dist_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("PADDING", (0, 0), (-1, -1), 5),
                ("TEXTCOLOR", (0, 1), (0, 1), RISK_COLORS["low"]),
                ("TEXTCOLOR", (0, 2), (0, 2), RISK_COLORS["medium"]),
                ("TEXTCOLOR", (0, 3), (0, 3), RISK_COLORS["high"]),
                ("TEXTCOLOR", (0, 4), (0, 4), RISK_COLORS["critical"]),
                ("FONTNAME", (0, 1), (0, 4), "Helvetica-Bold"),
            ]
        )
    )
    story.append(dist_table)
    story.append(
        Paragraph(
            _safe(overview.get("scoring_note", "Illustrative screening scores only.")),
            small_style,
        )
    )

    # 5. Executive Summary
    story.append(Paragraph("3. Executive Summary", section_style))
    for block in executive_summary.split("\n\n"):
        cleaned = block.strip().replace("### ", "").replace("**", "")
        if cleaned:
            story.append(Paragraph(_safe(cleaned), body_style))

    # 6. Extracted Clause Details
    story.append(PageBreak())
    story.append(Paragraph("4. Extracted Clauses", section_style))
    clause_rows = [["ID", "Page", "Category", "Title & Description"]]
    for cl in clauses:
        desc = cl.get("description") or cl.get("original_text", "")[:160]
        clause_rows.append(
            [
                Paragraph(_safe(cl.get("clause_id")), small_style),
                Paragraph(str(cl.get("page_number", 1)), small_style),
                Paragraph(_safe(cl.get("category")), small_style),
                Paragraph(f"<b>{_safe(cl.get('title'))}</b><br/>{_safe(desc)}", small_style),
            ]
        )
    clause_table = Table(clause_rows, colWidths=[0.7 * inch, 0.55 * inch, 1.35 * inch, 4.4 * inch], repeatRows=1)
    clause_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(clause_table)

    # 7. Risk Assessment
    story.append(Paragraph("5. Detailed Risk Assessment", section_style))
    for rf in risk_results:
        level = str(rf.get("risk_level", "low")).lower()
        verified_tag = "Verified" if rf.get("verified", True) else "Unverified"
        story.append(
            Paragraph(
                f"<b>{_safe(rf.get('clause_id'))} — {_safe(rf.get('risk_title'))}</b> "
                f"[{level.upper()} | Score: {rf.get('risk_score')}/100 | Page {rf.get('page_number')} | {verified_tag}]",
                body_style,
            )
        )
        story.append(Paragraph(f"<b>Explanation:</b> {_safe(rf.get('explanation'))}", small_style))
        story.append(Paragraph(f"<b>Potential Impact:</b> {_safe(rf.get('potential_impact'))}", small_style))
        story.append(Paragraph(f"<b>Suggested Action:</b> {_safe(rf.get('suggested_action'))}", small_style))
        story.append(Spacer(1, 4))

    # 8. Reference Template Comparisons
    story.append(Paragraph("6. Reference Template Comparisons (Illustrative Only)", section_style))
    if comparisons:
        for comp in comparisons:
            diffs = "; ".join(comp.get("differences", []))
            story.append(
                Paragraph(
                    f"<b>{_safe(comp.get('clause_id'))}</b> vs. <i>{_safe(comp.get('reference_source'))}</i> "
                    f"({_safe(comp.get('jurisdiction'))}): {_safe(diffs)}",
                    small_style,
                )
            )
            story.append(
                Paragraph(
                    f"<b>Recommendation:</b> {_safe(comp.get('recommendation'))}",
                    small_style,
                )
            )
    else:
        story.append(Paragraph("No reference comparisons were generated for this document.", body_style))

    # 9. Missing Clause Categories
    story.append(Paragraph("7. Missing or Uncertain Clause Categories", section_style))
    missing_list = missing_clauses.get("missing_categories", [])
    if missing_list:
        for item in missing_list:
            story.append(
                Paragraph(
                    f"<b>{_safe(item.get('category'))}</b> [{_safe(item.get('status'))}]: "
                    f"{_safe(item.get('explanation'))}",
                    small_style,
                )
            )
    else:
        story.append(Paragraph("All expected checklist categories for this contract type were detected.", body_style))

    # 10. Suggested Review Points & 11. Legal Disclaimer
    story.append(Paragraph("8. Suggested Review Points for Legal Counsel", section_style))
    story.append(
        Paragraph(
            "1. Review all Critical and High findings along with exact page references.<br/>"
            "2. Confirm whether missing categories (such as Dispute Resolution or Data Protection) are needed.<br/>"
            "3. Compare liability caps, indemnity symmetry, and auto-renewal notice terms against commercial tolerances.",
            body_style,
        )
    )

    story.append(Paragraph("9. Legal Disclaimer", section_style))
    story.append(Paragraph(_safe(LEGAL_DISCLAIMER), small_style))

    pdf_doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    pdf_doc.build(
        story,
        onFirstPage=lambda c, d: _draw_header_footer(c, d, doc_id),
        onLaterPages=lambda c, d: _draw_header_footer(c, d, doc_id),
    )
    return output_path

