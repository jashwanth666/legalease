"""Pydantic schemas for risk factors, findings, and overall risk overview."""

from typing import Literal
from pydantic import BaseModel, Field


RiskLevel = Literal["no_notable_risk", "uncertain", "low", "medium", "high", "critical"]
FindingType = Literal["detected_risk", "no_notable_risk", "uncertain_finding", "missing_information"]


class RiskFactorInputs(BaseModel):
    """Four transparent scoring inputs (0-100 each) combined in Python."""

    severity: float = Field(..., ge=0.0, le=100.0)
    unfavorable_wording: float = Field(..., ge=0.0, le=100.0)
    missing_protections: float = Field(..., ge=0.0, le=100.0)
    ambiguity: float = Field(..., ge=0.0, le=100.0)


class GeminiSingleRiskAssessment(BaseModel):
    """Structured risk assessment output expected from Gemini per clause."""

    clause_id: str
    risk_title: str
    factors: RiskFactorInputs
    explanation: str
    potential_impact: str
    suggested_action: str
    finding_type: FindingType = "detected_risk"


class GeminiBatchRiskAssessment(BaseModel):
    """Batch structured risk output returned by Gemini."""

    findings: list[GeminiSingleRiskAssessment]


class RiskFinding(BaseModel):
    """Final validated clause risk finding with Python-calculated score and level."""

    clause_id: str
    risk_level: RiskLevel
    risk_score: float | None = Field(default=None, ge=0.0, le=100.0)
    risk_title: str
    original_clause: str
    explanation: str
    potential_impact: str
    suggested_action: str
    page_number: int | None = Field(default=None, ge=1)
    location_type: Literal["pdf_page", "docx_paragraph"] = "pdf_page"
    paragraph_index: int | None = Field(default=None, ge=1)
    section_title: str | None = None
    finding_type: FindingType = "detected_risk"
    analysis_source: Literal["gemini", "deterministic_fallback", "ai_unavailable"] = (
        "deterministic_fallback"
    )
    gemini_status: str | None = None
    fallback_reason: str | None = None
    scoring_breakdown: dict[str, float] = Field(default_factory=dict)
    verified: bool = True


class RiskOverview(BaseModel):
    """Aggregate illustrative risk summary for a contract."""

    overall_risk_score: float = Field(..., ge=0.0, le=100.0)
    overall_risk_level: RiskLevel
    total_clauses: int = 0
    scored_clauses_count: int = 0
    no_notable_risk_count: int = 0
    uncertain_count: int = 0
    low_count: int = 0
    medium_count: int = 0
    high_count: int = 0
    critical_count: int = 0
    scoring_note: str = (
        "Prototype illustrative screening scores (40% severity, 30% unfavorable wording, "
        "20% missing protections, 10% ambiguity). Not a legally validated standard."
    )
    scoring_limitations: str = (
        "Overall score reflects a weighted blend of peak detected clause risks and contract-wide "
        "flagged risk density. Ordinary clauses with 'no notable pattern detected' and uncertain "
        "clauses do not receive numerical safety scores; a low overall score does NOT prove a "
        "contract is legally safe or balanced."
    )

