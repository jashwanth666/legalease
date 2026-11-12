"""Document text extraction for PDF (PyMuPDF) and DOCX (python-docx)."""

import json
import re
from pathlib import Path
from statistics import median
from typing import Any

import docx
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
import pymupdf as fitz


HEADING_PATTERN = re.compile(
    r"^(?:(?:ARTICLE|SECTION|CLAUSE)\s+[IVXLC0-9]+(?:\.\d+)*|"
    r"[IVXLC]+(?:[.)]|\s+[-–—:])\s+[A-Za-z]|"
    r"\d+(?:\.\d+)*\.?\s+[A-Za-z]).{1,95}$"
)


class DocumentExtractionError(Exception):
    """Raised when document text extraction fails unexpectedly."""


def _is_probable_heading(text: str, font_size: float = 0.0, median_size: float = 0.0, is_bold: bool = False) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 110 or "\n" in stripped:
        return False
    if HEADING_PATTERN.match(stripped):
        return True
    if median_size > 0 and font_size >= median_size * 1.15 and len(stripped.split()) <= 12:
        return True
    if is_bold and len(stripped.split()) <= 10 and not stripped.endswith("."):
        return True
    if stripped.isupper() and 3 <= len(stripped) <= 70:
        return True
    return False


def _extract_pdf(file_path: Path) -> tuple[list[dict[str, Any]], bool, str | None]:
    doc = fitz.open(str(file_path))
    try:
        if doc.is_encrypted or doc.needs_pass:
            raise DocumentExtractionError("Encrypted PDFs cannot be extracted.")

        pages: list[dict[str, Any]] = []
        total_alnum = 0
        has_images = False

        for page_idx, page in enumerate(doc, start=1):
            page_dict = page.get_text("dict")
            blocks = page_dict.get("blocks", [])
            if page.get_images(full=False):
                has_images = True

            span_sizes: list[float] = []
            for block in blocks:
                if block.get("type") == 0:
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            if span.get("text", "").strip():
                                span_sizes.append(float(span.get("size", 10.0)))

            median_size = median(span_sizes) if span_sizes else 10.0
            paragraphs: list[str] = []
            headings: list[str] = []

            for block in blocks:
                if block.get("type") != 0:
                    continue
                block_lines: list[str] = []
                block_sizes: list[float] = []
                bold_chars = 0
                total_chars = 0

                for line in block.get("lines", []):
                    line_parts: list[str] = []
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if text:
                            line_parts.append(text)
                            cleaned = text.strip()
                            if cleaned:
                                block_sizes.append(float(span.get("size", median_size)))
                                flags = int(span.get("flags", 0))
                                font_name = str(span.get("font", "")).lower()
                                is_span_bold = bool(flags & 16) or ("bold" in font_name)
                                total_chars += len(cleaned)
                                if is_span_bold:
                                    bold_chars += len(cleaned)
                    joined_line = "".join(line_parts).strip()
                    if joined_line:
                        block_lines.append(joined_line)

                if not block_lines:
                    continue

                block_text = " ".join(block_lines)
                block_text = re.sub(r"\s+", " ", block_text).strip()
                avg_size = sum(block_sizes) / len(block_sizes) if block_sizes else median_size
                is_bold = total_chars > 0 and (bold_chars / total_chars) >= 0.7

                if _is_probable_heading(block_text, avg_size, median_size, is_bold):
                    headings.append(block_text)

                paragraphs.append(block_text)

            page_text = "\n\n".join(paragraphs).strip()
            total_alnum += sum(ch.isalnum() for ch in page_text)
            pages.append(
                {
                    "page_number": page_idx,
                    "location_type": "pdf_page",
                    "paragraph_index": None,
                    "section_title": headings[0] if headings else None,
                    "text": page_text,
                    "headings": headings,
                }
            )

        ocr_required = total_alnum < 25
        warning = None
        if ocr_required:
            if has_images:
                warning = (
                    "No usable selectable text was detected in this scanned PDF. "
                    "OCR is required before clause analysis (OCR is planned as a future enhancement)."
                )
            else:
                warning = (
                    "No usable selectable text was detected in this PDF. "
                    "OCR or a text-based PDF is required."
                )

        return pages, ocr_required, warning
    finally:
        doc.close()


def _iter_docx_block_items(parent: DocxDocument):
    body = parent.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _extract_docx(file_path: Path) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Extract ordered DOCX paragraphs and tables using paragraph positions (no invented page numbers)."""
    document = docx.Document(str(file_path))
    blocks: list[dict[str, Any]] = []
    headings: list[str] = []
    total_alnum = 0
    paragraph_counter = 0
    current_section: str | None = None

    for item in _iter_docx_block_items(document):
        if isinstance(item, Paragraph):
            text = re.sub(r"\s+", " ", item.text or "").strip()
            if not text:
                continue

            paragraph_counter += 1
            style_name = (item.style.name if item.style else "") or ""
            is_heading_style = style_name.lower().startswith("heading") or style_name.lower() == "title"
            is_bold = bool(item.runs) and all(
                bool(r.bold) for r in item.runs if r.text.strip()
            )
            is_heading = is_heading_style or _is_probable_heading(text, is_bold=is_bold)
            if is_heading:
                headings.append(text)
                current_section = text

            blocks.append(
                {
                    "paragraph_index": paragraph_counter,
                    "location_type": "docx_paragraph",
                    "section_title": current_section,
                    "text": text,
                    "is_heading": is_heading,
                }
            )
            total_alnum += sum(ch.isalnum() for ch in text)

        elif isinstance(item, Table):
            table_rows: list[str] = []
            for row in item.rows:
                cells = [
                    re.sub(r"\s+", " ", cell.text or "").strip()
                    for cell in row.cells
                ]
                if any(cells):
                    row_line = " | ".join(cells)
                    table_rows.append(row_line)
                    total_alnum += sum(ch.isalnum() for ch in row_line)
            if table_rows:
                paragraph_counter += 1
                blocks.append(
                    {
                        "paragraph_index": paragraph_counter,
                        "location_type": "docx_paragraph",
                        "section_title": current_section,
                        "text": "\n".join(table_rows),
                        "is_heading": False,
                    }
                )

    combined_text = "\n\n".join(b["text"] for b in blocks).strip()
    pages: list[dict[str, Any]] = [
        {
            "page_number": None,
            "location_type": "docx_paragraph",
            "paragraph_index": blocks[0]["paragraph_index"] if blocks else 1,
            "section_title": blocks[0]["section_title"] if blocks else None,
            "text": combined_text,
            "headings": headings,
            "blocks": blocks,
        }
    ]

    ocr_required = total_alnum < 10
    warning = (
        "No usable text was detected in this DOCX document."
        if ocr_required
        else None
    )
    return pages, ocr_required, warning


def extract_document_text(
    file_path: Path,
    document_id: str,
    original_filename: str,
    file_type: str | None = None,
) -> dict[str, Any]:
    """Extract structured location-referenced text from a PDF or DOCX file."""
    resolved_type = (file_type or file_path.suffix.lstrip(".")).lower()

    if resolved_type == "pdf":
        pages, ocr_required, warning = _extract_pdf(file_path)
        page_count = len(pages)
        full_text = "\n\n".join(
            f"[Page {page['page_number']}]\n{page['text']}"
            for page in pages
            if page["text"]
        ).strip()
    elif resolved_type == "docx":
        pages, ocr_required, warning = _extract_docx(file_path)
        # DOCX files do not have fixed page layout; keep page_count=0 rather than fabricating pages.
        page_count = 0
        blocks = pages[0].get("blocks", []) if pages else []
        full_text = "\n\n".join(
            f"[Paragraph {b['paragraph_index']}]\n{b['text']}"
            for b in blocks
            if b.get("text")
        ).strip()
    else:
        raise DocumentExtractionError(f"Unsupported file type for extraction: {resolved_type}")

    return {
        "document_id": document_id,
        "filename": original_filename,
        "file_type": resolved_type,
        "page_count": page_count,
        "location_mode": "pdf_page" if resolved_type == "pdf" else "docx_paragraph",
        "ocr_required": ocr_required,
        "warning": warning,
        "pages": pages,
        "full_text": full_text,
    }


def save_extracted_document(extracted_data: dict[str, Any], extracted_dir: Path) -> Path:
    """Persist structured extracted text to JSON inside storage/extracted."""
    extracted_dir.mkdir(parents=True, exist_ok=True)
    output_path = extracted_dir / f"{extracted_data['document_id']}.json"
    output_path.write_text(
        json.dumps(extracted_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path


def load_extracted_document(document_id: str, extracted_dir: Path) -> dict[str, Any] | None:
    """Load extracted document JSON if present."""
    path = extracted_dir / f"{document_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
