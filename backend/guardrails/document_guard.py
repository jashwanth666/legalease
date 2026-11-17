"""Security and validation guardrails for uploaded legal documents."""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import docx
import pymupdf as fitz


MAX_PDF_PAGES = 500
MAX_DOCX_ENTRIES = 500
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB decompression guard
MAX_DOCX_COMPRESSION_RATIO = 100


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
        if doc.page_count > MAX_PDF_PAGES:
            raise DocumentValidationError(
                f"The PDF exceeds the maximum allowed page limit ({MAX_PDF_PAGES} pages).",
                status_code=413,
            )
        return int(doc.page_count)
    finally:
        doc.close()


def _validate_docx_bytes(content: bytes) -> int:
    """Verify DOCX ZIP container structure, ZIP-bomb bounds, and python-docx readability."""
    if not content.startswith(b"PK\x03\x04"):
        raise DocumentValidationError(
            "File content does not match a valid DOCX archive.",
            status_code=400,
        )

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            infolist = zf.infolist()
            if len(infolist) > MAX_DOCX_ENTRIES:
                raise DocumentValidationError(
                    "The DOCX archive contains too many entries.",
                    status_code=400,
                )
            total_uncompressed = 0
            names: set[str] = set()
            for info in infolist:
                norm_name = info.filename.replace("\\", "/")
                if norm_name.startswith("/") or ".." in Path(norm_name).parts:
                    raise DocumentValidationError(
                        "Invalid DOCX archive entry path detected.",
                        status_code=400,
                    )
                total_uncompressed += max(0, int(info.file_size))
                if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise DocumentValidationError(
                        "The DOCX archive uncompressed size exceeds safety limits.",
                        status_code=413,
                    )
                if info.file_size > 1_000_000:
                    ratio = info.file_size / max(1, info.compress_size)
                    if ratio > MAX_DOCX_COMPRESSION_RATIO:
                        raise DocumentValidationError(
                            "Suspicious compression ratio detected in DOCX archive.",
                            status_code=400,
                        )
                names.add(info.filename)

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

    # DOCX uses paragraph/section references rather than fixed page numbers.
    return 0


def resolve_contained_path(
    base_dir: Path, target_path: Path, tenant_id: str | None = None
) -> Path:
    """Verify target_path stays strictly inside base_dir (or base_dir/tenant_id) after symlink/path resolution."""
    effective_base = (base_dir / tenant_id) if tenant_id else base_dir
    base_resolved = effective_base.resolve()
    target_resolved = target_path.resolve()
    if not target_resolved.is_relative_to(base_resolved):
        raise DocumentValidationError(
            "Access denied: file path escapes managed application directory.",
            status_code=403,
        )
    return target_resolved


def safe_delete_file(
    base_dir: Path, target_path: Path, tenant_id: str | None = None
) -> bool:
    """Safely delete a file only if it resolves strictly inside base_dir or tenant subfolder."""
    resolved = resolve_contained_path(base_dir, target_path, tenant_id=tenant_id)
    if resolved.exists() and resolved.is_file():
        resolved.unlink(missing_ok=True)
        return True
    return False


def wrap_untrusted_contract_text(text: str) -> str:
    """Fence untrusted contract text so downstream prompts treat it strictly as data."""
    cleaned = text.replace("</untrusted_contract_text>", "[/untrusted_contract_text]")
    return (
        "<untrusted_contract_text>\n"
        f"{cleaned}\n"
        "</untrusted_contract_text>"
    )
