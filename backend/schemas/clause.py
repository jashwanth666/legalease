"""Pydantic schemas for extracted and classified legal clauses."""

from typing import Literal
from pydantic import BaseModel, Field


CLAUSE_CATEGORIES: tuple[str, ...] = (
    "Definitions",
    "Payment Terms",
    "Termination",
    "Liability",
    "Indemnification",
    "Confidentiality",
    "Intellectual Property",
    "Dispute Resolution",
    "Jurisdiction",
    "Renewal",
    "Non-Compete",
    "Data Protection",
    "Warranties",
    "Force Majeure",
)

ALL_CLAUSE_CATEGORIES: tuple[str, ...] = CLAUSE_CATEGORIES + ("Other",)


class ExtractedClause(BaseModel):
    """Represents a segmented clause with preserved original text and page reference."""

    clause_id: str
    title: str
    category: str
    original_text: str
    page_number: int = Field(..., ge=1)


class ClauseClassification(BaseModel):
    """Validated classification output for a single legal clause."""

    clause_id: str
    category: str
    description: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    classification_source: Literal["gemini", "deterministic_fallback", "ai_unavailable"] = (
        "deterministic_fallback"
    )
    uncertain: bool = False


class GeminiSingleClassification(BaseModel):
    """Structured output schema requested from Gemini for a single clause."""

    clause_id: str
    category: str = Field(
        description=(
            "One of: Definitions, Payment Terms, Termination, Liability, Indemnification, "
            "Confidentiality, Intellectual Property, Dispute Resolution, Jurisdiction, "
            "Renewal, Non-Compete, Data Protection, Warranties, Force Majeure, Other"
        )
    )
    description: str = Field(
        description="Concise plain-English 1-2 sentence summary of what the clause does."
    )
    confidence: float = Field(..., ge=0.0, le=1.0)


class GeminiBatchClassification(BaseModel):
    """Batch structured output schema for multiple clauses."""

    classifications: list[GeminiSingleClassification]

