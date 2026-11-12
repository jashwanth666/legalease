"""Document upload, listing, retrieval, and deletion endpoints."""

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.agents.extraction_agent import ExtractionAgent
from backend.config import Settings, get_settings
from backend.database import Document, get_db
from backend.guardrails.document_guard import (
    DocumentValidationError,
    resolve_contained_path,
    safe_delete_file,
    sanitize_filename,
    validate_uploaded_document,
)
from backend.ingestion.document_loader import (
    DocumentExtractionError,
    load_extracted_document,
)
from backend.schemas.report import (
    DeleteDocumentResponse,
    DocumentDetailResponse,
    DocumentSummary,
    UploadDocumentResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Documents"])
_extraction_agent = ExtractionAgent()


def _generate_document_id() -> str:
    return f"DOC-{uuid4().hex[:8].upper()}"


async def _read_upload_in_chunks(
    file: UploadFile, max_size_bytes: int, chunk_size: int = 65536
) -> bytes:
    """Read uploaded bytes incrementally and abort as soon as max_size_bytes is exceeded."""
    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_size_bytes:
            max_mb = max_size_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds the maximum allowed upload size of {max_mb} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/upload",
    response_model=UploadDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_contract(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Validate, securely store, and extract location-referenced text from an uploaded PDF/DOCX."""
    safe_name = sanitize_filename(file.filename)
    ext = Path(safe_name).suffix.lower()
    if ext not in {".pdf", ".docx"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Only PDF (.pdf) and Word (.docx) documents are allowed.",
        )

    raw_bytes = await _read_upload_in_chunks(file, settings.max_upload_size_bytes)

    try:
        validated = validate_uploaded_document(
            filename=file.filename,
            content=raw_bytes,
            max_size_bytes=settings.max_upload_size_bytes,
        )
    except DocumentValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    document_id = _generate_document_id()
    stored_filename = f"{document_id}{validated.extension}"
    stored_path = resolve_contained_path(settings.upload_dir, settings.upload_dir / stored_filename)

    try:
        settings.ensure_directories()
        stored_path.write_bytes(raw_bytes)
        extracted = _extraction_agent.run(
            file_path=stored_path,
            document_id=document_id,
            filename=validated.safe_filename,
            file_type=validated.file_type,
            extracted_dir=settings.extracted_dir,
        )
    except DocumentExtractionError as exc:
        if stored_path.exists():
            stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        if stored_path.exists():
            stored_path.unlink(missing_ok=True)
        logger.exception("Unexpected error processing upload %s", document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store or extract uploaded document.",
        ) from exc

    ocr_required = bool(extracted.get("ocr_required", False))
    processing_status = "ocr_required" if ocr_required else "uploaded"
    page_count = int(extracted.get("page_count", validated.page_count))

    db_doc = Document(
        document_id=document_id,
        filename=validated.safe_filename,
        stored_filename=stored_filename,
        file_type=validated.file_type,
        file_size=validated.file_size,
        processing_status=processing_status,
        page_count=page_count,
        ocr_required=ocr_required,
    )
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    logger.info(
        "Uploaded document_id=%s file_type=%s pages=%s ocr_required=%s",
        document_id,
        validated.file_type,
        page_count,
        ocr_required,
    )

    message = (
        extracted["warning"]
        if ocr_required and extracted.get("warning")
        else "Document uploaded and text extracted successfully. Click 'Analyze Contract' to run AI analysis."
    )

    return UploadDocumentResponse(
        document_id=db_doc.document_id,
        filename=db_doc.filename,
        file_type=db_doc.file_type,
        file_size=db_doc.file_size,
        upload_date=db_doc.upload_date,
        processing_status=db_doc.processing_status,
        page_count=db_doc.page_count,
        ocr_required=db_doc.ocr_required,
        warning=extracted.get("warning"),
        message=message,
    )


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(db: Session = Depends(get_db)):
    """List all uploaded documents ordered newest first."""
    docs = db.query(Document).order_by(Document.upload_date.desc()).all()
    return [DocumentSummary.model_validate(doc) for doc in docs]


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Return metadata and extracted page text for a specific document."""
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    extracted = load_extracted_document(document_id, settings.extracted_dir)
    return DocumentDetailResponse(
        document=DocumentSummary.model_validate(doc),
        extracted=extracted,
    )


@router.delete("/documents/{document_id}", response_model=DeleteDocumentResponse)
def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Delete a document record along with uploaded, extracted, and report files."""
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    safe_delete_file(settings.upload_dir, settings.upload_dir / doc.stored_filename)
    safe_delete_file(settings.extracted_dir, settings.extracted_dir / f"{document_id}.json")

    for report in list(doc.reports):
        try:
            safe_delete_file(settings.reports_dir, Path(report.report_path))
        except DocumentValidationError:
            logger.warning("Skipped out-of-bounds report path during delete for %s", document_id)

    db.delete(doc)
    db.commit()

    logger.info("Deleted document_id=%s and associated files", document_id)
    return DeleteDocumentResponse(
        document_id=document_id,
        deleted=True,
        message=f"Document '{document_id}' and associated artifacts were deleted.",
    )

