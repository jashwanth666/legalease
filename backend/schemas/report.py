"""Pydantic response and data schemas for documents, extracted pages, and reports."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str
    version: str
    gemini_configured: bool
    disclaimer: str


class ExtractedPage(BaseModel):
    page_number: int | None = Field(default=None, ge=1)
    location_type: str = "pdf_page"
    paragraph_index: int | None = None
    section_title: str | None = None
    text: str
    headings: list[str] = Field(default_factory=list)


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    filename: str
    file_type: str
    file_size: int
    upload_date: datetime
    processing_status: str
    page_count: int = 0
    ocr_required: bool = False
    detected_contract_type: str | None = None
    overall_risk_score: float | None = None
    overall_risk_level: str | None = None
    analysis_mode: str | None = None
    gemini_status: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    last_error: str | None = None
    embedding_backend: str | None = None


class UploadDocumentResponse(BaseModel):
    document_id: str
    filename: str
    file_type: str
    file_size: int
    upload_date: datetime
    processing_status: str
    page_count: int
    ocr_required: bool
    warning: str | None = None
    message: str


class DocumentDetailResponse(BaseModel):
    document: DocumentSummary
    extracted: dict[str, Any] | None = None


class DeleteDocumentResponse(BaseModel):
    document_id: str
    deleted: bool
    message: str

