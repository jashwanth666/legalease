"""Legal clause splitting module preserving complete clause text and page numbers."""

import re
from typing import Any

from backend.schemas.clause import CLAUSE_CATEGORIES, ExtractedClause


SECTION_HEADER_RE = re.compile(
    r"^(?:"
    r"(?:ARTICLE|SECTION|CLAUSE)\s+[IVXLC0-9]+(?:\.\d+)*(?:[\s:.\-–—]+.*)?|"
    r"[IVXLC]+(?:[.)]|\s+[-–—:])\s+[A-Za-z][^\n]{1,95}|"
    r"\d+(?:\.\d+)*\.?\s+[A-Za-z][^\n]{1,95}|"
    r"[A-Z]\.\s+[A-Za-z][^\n]{1,85}"
    r")$"
)

INLINE_HEADER_PUNCT_RE = re.compile(
    r"^((?:(?:ARTICLE|SECTION|CLAUSE)\s+[IVXLC0-9]+(?:\.\d+)*|[IVXLC]+[.)]|\d+(?:\.\d+)*\.?)\s+"
    r"[A-Za-z][A-Za-z0-9 &,/()-]{2,65})[:.\-–—]+\s+(.+)$",
    re.DOTALL,
)

INLINE_HEADER_CAPS_RE = re.compile(
    r"^((?:(?:ARTICLE|SECTION|CLAUSE)\s+[IVXLC0-9]+(?:\.\d+)*|[IVXLC]+[.)]|\d+(?:\.\d+)*\.?)\s+"
    r"[A-Z][A-Z0-9 &,/()-]{2,55})\s+([A-Z][a-z].+)$",
    re.DOTALL,
)

MID_PARA_HEADING_SPLIT_RE = re.compile(
    r"(?<=[.!?;])\s+(?=(?:"
    r"\d+(?:\.\d+)*\.?\s+[A-Z][A-Z0-9 &,/()-]{2,45}(?:\s+[A-Z][a-z]|[:.\-–—])|"
    r"(?:ARTICLE|SECTION|CLAUSE)\s+[IVXLC0-9]+\b|"
    r"[IVXLC]+\.\s+[A-Z][A-Z\s]{2,40}"
    r"))"
)

PAGE_MARKER_RE = re.compile(r"^(?:page\s+\d+(?:\s+of\s+\d+)?|\-\s*\d+\s*\-)$", re.IGNORECASE)
SIGNATURE_LINE_RE = re.compile(
    r"^(?:by|name|title|date|signature|witness|executed as of|authorized signatory)\s*[:_].*|"
    r"^_{4,}.*",
    re.IGNORECASE,
)

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Definitions": (
        "definition",
        "definitions",
        "means",
        "shall mean",
        "defined terms",
        "interpretation",
    ),
    "Payment Terms": (
        "payment",
        "fees",
        "invoice",
        "compensation",
        "billing",
        "interest",
        "late fee",
        "hourly rate",
        "pricing",
        "remuneration",
    ),
    "Termination": (
        "termination",
        "terminate",
        "cancellation",
        "cancel",
        "expiration",
        "survival",
        "notice of termination",
    ),
    "Liability": (
        "limitation of liability",
        "liability",
        "consequential damages",
        "aggregate liability",
        "indirect damages",
        "not exceed",
    ),
    "Indemnification": (
        "indemnification",
        "indemnify",
        "hold harmless",
        "defend",
        "third-party claims",
    ),
    "Confidentiality": (
        "confidential",
        "confidentiality",
        "non-disclosure",
        "disclosing party",
        "receiving party",
        "proprietary information",
        "trade secret",
    ),
    "Intellectual Property": (
        "intellectual property",
        "copyright",
        "patent",
        "trademark",
        "deliverables",
        "ownership",
        "pre-existing",
        "work product",
        "license",
    ),
    "Dispute Resolution": (
        "dispute resolution",
        "arbitration",
        "mediation",
        "arbitrator",
        "good faith negotiation",
        "settlement",
    ),
    "Jurisdiction": (
        "jurisdiction",
        "governing law",
        "venue",
        "courts of",
        "state of",
        "conflict of law",
        "exclusive jurisdiction",
    ),
    "Renewal": (
        "renewal",
        "automatically renew",
        "auto-renew",
        "successive",
        "non-renewal",
        "extension of term",
    ),
    "Non-Compete": (
        "non-compete",
        "noncompete",
        "non-solicitation",
        "competing",
        "restrictive covenant",
        "solicit",
    ),
    "Data Protection": (
        "data protection",
        "personal data",
        "privacy",
        "gdpr",
        "ccpa",
        "data processing",
        "security breach",
        "pii",
    ),
    "Warranties": (
        "warranties",
        "warranty",
        "as is",
        "merchantability",
        "fitness for a particular purpose",
        "representations and warranties",
    ),
    "Force Majeure": (
        "force majeure",
        "beyond its reasonable control",
        "act of god",
        "natural disaster",
        "war",
        "pandemic",
    ),
}


def infer_clause_category(title: str, text: str) -> tuple[str, float]:
    """Deterministic keyword-based category inference with confidence score."""
    title_l = title.lower()
    text_l = text.lower()

    best_cat = "Other"
    best_score = 0.0

    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0.0
        for kw in keywords:
            if kw in title_l:
                score += 3.0
            if kw in text_l:
                score += 1.0
        if score > best_score:
            best_score = score
            best_cat = category

    if best_cat == "Other":
        return "Other", 0.35

    confidence = min(0.92, 0.55 + 0.08 * best_score)
    return best_cat, round(confidence, 2)


def _is_document_banner(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if len(stripped) > 120:
        return False
    lower = stripped.lower()
    if lower in {"(sample)", "sample", "[draft]", "draft", "(draft)", "(specimen)", "confidential"}:
        return True
    banner_terms = (
        "non-disclosure agreement",
        "service agreement",
        "employment agreement",
        "partnership agreement",
        "confidentiality agreement",
        "master services agreement",
        "consulting agreement",
    )
    return (stripped.isupper() or "(sample)" in lower or len(stripped.split()) <= 6) and any(
        term in lower for term in banner_terms
    )


def _is_non_clause_boilerplate(paragraph: str) -> bool:
    """Detect page footers or standalone signature-block boilerplate that are not contract clauses."""
    stripped = paragraph.strip()
    if not stripped:
        return True
    if PAGE_MARKER_RE.match(stripped):
        return True
    lower = stripped.lower()
    if lower.startswith("in witness whereof"):
        return True
    if SIGNATURE_LINE_RE.match(stripped) and len(stripped) < 160:
        return True
    # Pure date/party header lines under ~10 words at start of title page
    if len(stripped.split()) <= 8 and any(
        lower.startswith(prefix) for prefix in ("effective date:", "prepared for:", "confidential draft")
    ):
        return True
    return False


def _is_heading_paragraph(paragraph: str, page_headings: set[str]) -> bool:
    stripped = paragraph.strip()
    if not stripped or len(stripped) > 130 or "\n" in stripped:
        return False
    if stripped in page_headings and len(stripped.split()) <= 14:
        return True
    if SECTION_HEADER_RE.match(stripped) and not stripped.endswith("."):
        return True
    if re.match(r"^(?:\d+(?:\.\d+)*\.?|[IVXLC]+[.)])\s+[A-Z][A-Za-z0-9 &,/()-]{2,85}$", stripped):
        return True
    if stripped.isupper() and 4 <= len(stripped) <= 65 and not stripped.endswith("."):
        return True
    lower = stripped.lower().rstrip(":")
    if any(lower == cat.lower() for cat in CLAUSE_CATEGORIES):
        return True
    return False


def _match_inline_heading(paragraph: str) -> tuple[str, str] | None:
    m_punct = INLINE_HEADER_PUNCT_RE.match(paragraph)
    if m_punct:
        return m_punct.group(1).strip(), m_punct.group(2).strip()
    m_caps = INLINE_HEADER_CAPS_RE.match(paragraph)
    if m_caps:
        return m_caps.group(1).strip(), m_caps.group(2).strip()
    return None


def _expand_page_units(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand a PDF page or DOCX document segment into ordered heading/paragraph units."""
    location_type = page.get("location_type") or (
        "docx_paragraph" if page.get("page_number") is None else "pdf_page"
    )
    page_number = page.get("page_number")
    if page_number is not None:
        page_number = int(page_number)
    page_headings = {h.strip() for h in page.get("headings", []) if h}

    raw_units: list[dict[str, Any]] = []
    if location_type == "docx_paragraph" and page.get("blocks"):
        for block in page["blocks"]:
            txt = (block.get("text") or "").strip()
            if not txt:
                continue
            raw_units.append(
                {
                    "text": txt,
                    "page_number": None,
                    "location_type": "docx_paragraph",
                    "paragraph_index": int(block.get("paragraph_index", 1)),
                    "section_title": block.get("section_title"),
                    "is_heading_hint": bool(block.get("is_heading", False)),
                }
            )
    else:
        page_text = (page.get("text") or "").strip()
        if not page_text:
            return []
        for idx, rp in enumerate(re.split(r"\n{2,}", page_text), start=1):
            rp = rp.strip()
            if not rp:
                continue
            if "\n" in rp:
                first_line, rest = rp.split("\n", 1)
                if _is_heading_paragraph(first_line.strip(), page_headings) and rest.strip():
                    raw_units.append(
                        {
                            "text": first_line.strip(),
                            "page_number": page_number,
                            "location_type": location_type,
                            "paragraph_index": idx if location_type == "docx_paragraph" else None,
                            "section_title": first_line.strip(),
                            "is_heading_hint": True,
                        }
                    )
                    raw_units.append(
                        {
                            "text": rest.strip(),
                            "page_number": page_number,
                            "location_type": location_type,
                            "paragraph_index": idx if location_type == "docx_paragraph" else None,
                            "section_title": first_line.strip(),
                            "is_heading_hint": False,
                        }
                    )
                    continue
            raw_units.append(
                {
                    "text": rp,
                    "page_number": page_number,
                    "location_type": location_type,
                    "paragraph_index": idx if location_type == "docx_paragraph" else None,
                    "section_title": page.get("section_title"),
                    "is_heading_hint": False,
                }
            )

    expanded: list[dict[str, Any]] = []
    for unit in raw_units:
        parts = [p.strip() for p in MID_PARA_HEADING_SPLIT_RE.split(unit["text"]) if p.strip()]
        if len(parts) > 1:
            for part in parts:
                expanded.append({**unit, "text": part, "is_heading_hint": False})
        else:
            expanded.append(unit)
    return expanded


def split_pages_into_clauses(pages: list[dict[str, Any]]) -> list[ExtractedClause]:
    """Split extracted document pages/paragraphs into complete legal clauses with location metadata."""
    raw_clauses: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_signature_block = False

    for page in pages:
        page_headings = {h.strip() for h in page.get("headings", []) if h}
        units = _expand_page_units(page)

        for unit in units:
            para = unit["text"]
            page_number = unit["page_number"]
            location_type = unit["location_type"]
            paragraph_index = unit["paragraph_index"]
            section_title = unit["section_title"]

            if not raw_clauses and current is None and _is_document_banner(para):
                continue

            if _is_non_clause_boilerplate(para):
                if para.lower().startswith("in witness whereof"):
                    in_signature_block = True
                continue

            if in_signature_block and len(para.split()) <= 10 and not _match_inline_heading(para):
                # Short signature block fields after IN WITNESS WHEREOF
                if not _is_heading_paragraph(para, page_headings):
                    continue
            in_signature_block = False

            inline = _match_inline_heading(para)
            if inline:
                if current and current["body_parts"]:
                    raw_clauses.append(current)
                title, _body = inline
                current = {
                    "title": title,
                    "page_number": page_number,
                    "end_page_number": page_number,
                    "location_type": location_type,
                    "paragraph_index": paragraph_index,
                    "section_title": section_title or title,
                    "body_parts": [para],
                    "has_explicit_heading": True,
                }
                continue

            if unit.get("is_heading_hint") or _is_heading_paragraph(para, page_headings):
                if current and (current["body_parts"] or current["title"]):
                    raw_clauses.append(current)
                current = {
                    "title": para,
                    "page_number": page_number,
                    "end_page_number": page_number,
                    "location_type": location_type,
                    "paragraph_index": paragraph_index,
                    "section_title": section_title or para,
                    "body_parts": [],
                    "has_explicit_heading": True,
                }
                continue

            if current is None:
                inferred_cat, _ = infer_clause_category("", para)
                loc_label = (
                    f"Page {page_number}"
                    if page_number is not None
                    else f"Paragraph {paragraph_index or 1}"
                )
                inferred_title = (
                    inferred_cat
                    if inferred_cat != "Other"
                    else f"Unheaded Provision ({loc_label})"
                )
                current = {
                    "title": inferred_title,
                    "page_number": page_number,
                    "end_page_number": page_number,
                    "location_type": location_type,
                    "paragraph_index": paragraph_index,
                    "section_title": section_title,
                    "body_parts": [para],
                    "has_explicit_heading": False,
                }
            else:
                current["body_parts"].append(para)
                if page_number is not None:
                    current["end_page_number"] = page_number

    if current and (current["body_parts"] or current["title"]):
        raw_clauses.append(current)

    extracted: list[ExtractedClause] = []
    for idx, item in enumerate(raw_clauses, start=1):
        title = item["title"].strip()
        if item["body_parts"]:
            first_part = item["body_parts"][0]
            if first_part.startswith(title):
                full_text = "\n\n".join(item["body_parts"]).strip()
            else:
                full_text = f"{title}\n\n" + "\n\n".join(item["body_parts"]).strip()
        else:
            full_text = title

        category, _ = infer_clause_category(title, full_text)
        has_heading = bool(item.get("has_explicit_heading"))
        has_body = bool(item["body_parts"])

        seg_conf = "high"
        seg_uncertain = False
        seg_note = None
        if not has_heading:
            seg_conf = "medium"
            seg_uncertain = True
            seg_note = "No explicit numbered heading detected; clause boundary inferred from paragraph structure."
        elif not has_body:
            seg_conf = "low"
            seg_uncertain = True
            seg_note = "Heading detected without accompanying body paragraph."

        extracted.append(
            ExtractedClause(
                clause_id=f"CL-{idx:03d}",
                title=title,
                category=category,
                original_text=full_text,
                page_number=item["page_number"],
                end_page_number=item["end_page_number"],
                location_type=item["location_type"],
                paragraph_index=item["paragraph_index"],
                section_title=item["section_title"],
                segmentation_confidence=seg_conf,
                segmentation_uncertain=seg_uncertain,
                segmentation_note=seg_note,
            )
        )

    return extracted
