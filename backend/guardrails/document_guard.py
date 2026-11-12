"""Security and validation guardrails for uploaded legal documents."""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import docx
import pymupdf as fitz


class DocumentValidationError(Exception):
    """Raised when an uploaded file fails security, format, or integrity checks."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedUpload:
    """Validated upload metadata returned by document guardrails."""

    safe_filename: str
    file_type: str  # "pdf" or "docx"
    extension: str  # ".pdf" or ".docx"
    file_size: int
    page_count: int


def sanitize_filename(filename: str | None) -> str:
    """Normalize an uploaded filename to prevent path traversal and unsafe characters."""
    if not filename:
        return "uploaded_document"
    base = Path(filename).name.strip()
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)
    base = re.sub(r"\s+", "_", base)
    base = base.strip("._")
    if not base:
        return "uploaded_document"
    return base[:180]


def validate_uploaded_document(
    filename: str | None,
    content: bytes,
    max_size_bytes: int,
) -> ValidatedUpload:
    """Validate filename, extension, size, magic bytes, and structural integrity."""
    safe_name = sanitize_filename(filename)
    ext = Path(safe_name).suffix.lower()

    if ext not in {".pdf", ".docx"}:
        raise DocumentValidationError(
            "Unsupported file type. Only PDF (.pdf) and Word (.docx) documents are allowed.",
            status_code=400,
        )

    file_size = len(content)
    if file_size == 0:
        raise DocumentValidationError(
            "The uploaded file is empty (0 bytes).",
            status_code=400,
        )

    if file_size > max_size_bytes:
        max_mb = max_size_bytes // (1024 * 1024)
        raise DocumentValidationError(
            f"File exceeds the maximum allowed upload size of {max_mb} MB.",
            status_code=413,
        )

    if ext == ".pdf":
        page_count = _validate_pdf_bytes(content)
        file_type = "pdf"
    else:
        page_count = _validate_docx_bytes(content)
        file_type = "docx"

    return ValidatedUpload(
        safe_filename=safe_name,
        file_type=file_type,
        extension=ext,
        file_size=file_size,
        page_count=page_count,
    )


def _validate_pdf_bytes(content: bytes) -> int:
    """Verify PDF magic header, non-encryption, and readable page structure."""
    if not content.lstrip().startswith(b"%PDF-"):
        raise DocumentValidationError(
            "File content does not match a valid PDF header.",
            status_code=400,
        )

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise DocumentValidationError(
            f"The PDF file appears corrupted and could not be opened: {exc}",
            status_code=400,
        ) from exc

    try:
        if doc.is_encrypted or doc.needs_pass:
            raise DocumentValidationError(
                "Encrypted or password-protected PDFs cannot be processed.",
                status_code=400,
            )
        if doc.page_count <= 0:
            raise DocumentValidationError(
                "The PDF contains no pages.",
                status_code=400,
            )
        return int(doc.page_count)
    finally:
        doc.close()


def _validate_docx_bytes(content: bytes) -> int:
    """Verify DOCX ZIP container structure and python-docx readability."""
    if not content.startswith(b"PK\x03\x04"):
        raise DocumentValidationError(
            "File content does not match a valid DOCX archive.",
            status_code=400,
        )

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise DocumentValidationError(
                    "Invalid DOCX structure: missing word/document.xml.",
                    status_code=400,
                )
    except DocumentValidationError:
        raise
    except Exception as exc:
        raise DocumentValidationError(
            f"The DOCX file appears corrupted or is not a valid ZIP archive: {exc}",
            status_code=400,
        ) from exc

    try:
        document = docx.Document(io.BytesIO(content))
        if not document.paragraphs and not document.tables:
            raise DocumentValidationError(
                "The DOCX document contains no readable paragraphs or tables.",
                status_code=400,
            )
    except DocumentValidationError:
        raise
    except Exception as exc:
        raise DocumentValidationError(
            f"Could not parse DOCX document: {exc}",
            status_code=400,
        ) from exc

    # DOCX does not embed fixed pagination like PDF; loader calculates logical pages.
    return 1


def wrap_untrusted_contract_text(text: str) -> str:
    """Fence untrusted contract text so downstream prompts treat it strictly as data."""
    cleaned = text.replace("</untrusted_contract_text>", "[/untrusted_contract_text]")
    return (
        "<untrusted_contract_text>\n"
        f"{cleaned}\n"
        "</untrusted_contract_text>"
    )
