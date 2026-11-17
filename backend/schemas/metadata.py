"""Pydantic schemas for structured contract metadata extraction and evidence verification."""

from typing import Any, Literal
from pydantic import BaseModel, Field


LocationType = Literal["pdf_page", "docx_paragraph"]


class MetadataItem(BaseModel):
    """Represents a single extracted metadata field with grounded evidence."""

    field_name: str
    value: str | list[str] | float | int | None = None
    source_quote: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    paragraph_index: int | None = Field(default=None, ge=1)
    location_type: LocationType = "pdf_page"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    verified: bool = False
    is_uncertain: bool = False
    is_missing: bool = False
    notes: str | None = None


class ContractMetadata(BaseModel):
    """Complete 16-field structured metadata extraction for a contract."""

    document_id: str
    contract_title_and_type: MetadataItem
    party_names_and_roles: MetadataItem
    effective_date: MetadataItem
    expiration_date: MetadataItem
    contract_duration: MetadataItem
    renewal_date_and_conditions: MetadataItem
    contract_value: MetadataItem
    payment_terms: MetadataItem
    governing_law_and_jurisdiction: MetadataItem
    notice_period: MetadataItem
    termination_conditions: MetadataItem
    liability_limitations: MetadataItem
    indemnification_terms: MetadataItem
    deliverables_and_responsibilities: MetadataItem
    confidentiality_period: MetadataItem
    dispute_resolution_method: MetadataItem
    extraction_source: Literal["gemini", "deterministic_fallback", "ai_unavailable"] = (
        "deterministic_fallback"
    )
    completeness_score: float = Field(default=0.0, ge=0.0, le=1.0)

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata model to dictionary."""
        return self.model_dump()


class GeminiMetadataField(BaseModel):
    """Schema for individual field extracted by Gemini."""

    value: str | None = Field(
        default=None,
        description="Extracted value, or null if not explicitly stated in the document.",
    )
    source_quote: str | None = Field(
        default=None,
        description="Exact verbatim excerpt from the document providing proof, or null if missing.",
    )
    page_or_paragraph: int | None = Field(
        default=None,
        description="Page number or paragraph index where the quote is located.",
    )
    confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0.",
    )
    is_missing: bool = Field(
        default=False,
        description="Set to true if this information is not found in the contract.",
    )
    is_uncertain: bool = Field(
        default=False,
        description="Set to true if the text is ambiguous or unclear.",
    )


class GeminiContractMetadataExtraction(BaseModel):
    """Gemini structured output schema for all 16 contract metadata fields."""

    contract_title_and_type: GeminiMetadataField
    party_names_and_roles: GeminiMetadataField
    effective_date: GeminiMetadataField
    expiration_date: GeminiMetadataField
    contract_duration: GeminiMetadataField
    renewal_date_and_conditions: GeminiMetadataField
    contract_value: GeminiMetadataField
    payment_terms: GeminiMetadataField
    governing_law_and_jurisdiction: GeminiMetadataField
    notice_period: GeminiMetadataField
    termination_conditions: GeminiMetadataField
    liability_limitations: GeminiMetadataField
    indemnification_terms: GeminiMetadataField
    deliverables_and_responsibilities: GeminiMetadataField
    confidentiality_period: GeminiMetadataField
    dispute_resolution_method: GeminiMetadataField
