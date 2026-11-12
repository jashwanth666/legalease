"""Legal clause splitting module preserving complete clause text and page numbers."""

import re
from typing import Any

from backend.schemas.clause import CLAUSE_CATEGORIES, ExtractedClause


SECTION_HEADER_RE = re.compile(
    r"^(?:(?:ARTICLE|SECTION|CLAUSE)\s+[IVXLC0-9]+(?:\.\d+)*[\s:.\-–—]*.*|"
    r"\d+(?:\.\d+)*\.?\s+[A-Za-z][^\n]{1,95})$"
)

INLINE_HEADER_RE = re.compile(
    r"^((?:(?:ARTICLE|SECTION|CLAUSE)\s+[IVXLC0-9]+(?:\.\d+)*|\d+(?:\.\d+)*\.?)\s+"
    r"[A-Za-z][A-Za-z0-9 &,/()-]{2,60})[:.\-–—]+\s+(.+)$",
    re.DOTALL,
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
    banner_terms = (
        "non-disclosure agreement",
        "service agreement",
        "employment agreement",
        "partnership agreement",
        "confidentiality agreement",
        "master services agreement",
    )
    return (stripped.isupper() or "(sample)" in lower) and any(
        term in lower for term in banner_terms
    )


def _is_heading_paragraph(paragraph: str, page_headings: set[str]) -> bool:
    stripped = paragraph.strip()
    if not stripped or len(stripped) > 130 or "\n" in stripped:
        return False
    if stripped in page_headings:
        return True
    if SECTION_HEADER_RE.match(stripped) and not stripped.endswith("."):
        return True
    if re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9 &,/()-]{2,85}$", stripped):
        return True
    lower = stripped.lower()
    if any(lower == cat.lower() or lower.startswith(f"{cat.lower()}:") for cat in CLAUSE_CATEGORIES):
        return True
    return False


def split_pages_into_clauses(pages: list[dict[str, Any]]) -> list[ExtractedClause]:
    """Split extracted document pages into structured clauses with preserved text and page numbers."""
    raw_clauses: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for page in pages:
        page_number = int(page.get("page_number", 1))
        page_text = (page.get("text") or "").strip()
        if not page_text:
            continue

        page_headings = {h.strip() for h in page.get("headings", []) if h}
        raw_paragraphs = [p.strip() for p in re.split(r"\n{2,}", page_text) if p.strip()]
        paragraphs: list[str] = []
        for rp in raw_paragraphs:
            if "\n" in rp:
                first_line, rest = rp.split("\n", 1)
                if _is_heading_paragraph(first_line.strip(), page_headings) and rest.strip():
                    paragraphs.append(first_line.strip())
                    paragraphs.append(rest.strip())
                    continue
            paragraphs.append(rp)

        for para in paragraphs:
            if not raw_clauses and current is None and _is_document_banner(para):
                continue

            inline_match = INLINE_HEADER_RE.match(para)
            if inline_match:
                if current and current["body_parts"]:
                    raw_clauses.append(current)
                title = inline_match.group(1).strip()
                body = inline_match.group(2).strip()
                current = {
                    "title": title,
                    "page_number": page_number,
                    "body_parts": [para],
                    "body_only": [body],
                }
                continue

            if _is_heading_paragraph(para, page_headings):
                if current and current["body_parts"]:
                    raw_clauses.append(current)
                    current = None
                elif current and not current["body_parts"]:
                    # Consecutive heading without body: preserve previous heading if needed
                    raw_clauses.append(current)
                    current = None
                current = {
                    "title": para,
                    "page_number": page_number,
                    "body_parts": [],
                    "body_only": [],
                }
                continue

            if current is None:
                # Paragraph without preceding explicit heading: infer a concise title
                inferred_cat, _ = infer_clause_category("", para)
                inferred_title = (
                    inferred_cat
                    if inferred_cat != "Other"
                    else f"Clause on Page {page_number}"
                )
                current = {
                    "title": inferred_title,
                    "page_number": page_number,
                    "body_parts": [para],
                    "body_only": [para],
                }
            else:
                current["body_parts"].append(para)
                current["body_only"].append(para)

    if current and (current["body_parts"] or current["title"]):
        raw_clauses.append(current)

    extracted: list[ExtractedClause] = []
    for idx, item in enumerate(raw_clauses, start=1):
        title = item["title"].strip()
        if item["body_parts"]:
            # If title wasn't already duplicated in body_parts, include heading + body
            first_part = item["body_parts"][0]
            if first_part.startswith(title):
                full_text = "\n\n".join(item["body_parts"]).strip()
            else:
                full_text = f"{title}\n\n" + "\n\n".join(item["body_parts"]).strip()
        else:
            full_text = title

        category, _ = infer_clause_category(title, full_text)
        extracted.append(
            ExtractedClause(
                clause_id=f"CL-{idx:03d}",
                title=title,
                category=category,
                original_text=full_text,
                page_number=item["page_number"],
            )
        )

    return extracted
