"""SQLAlchemy ORM models for LegalEase."""

from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(String(32), nullable=False, default="employee")  # admin, legal_reviewer, employee
    tenant_id = Column(String(64), nullable=False, default="default_tenant", index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    documents = relationship("Document", back_populates="owner")

    __table_args__ = (
        Index("ix_users_tenant_role", "tenant_id", "role"),
    )


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(64), nullable=False, default="default_tenant", index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    document_id = Column(String(32), unique=True, nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    file_type = Column(String(16), nullable=False)
    file_size = Column(Integer, nullable=False)
    upload_date = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    processing_status = Column(String(32), default="uploaded", nullable=False)
    current_stage = Column(String(64), default="uploaded", nullable=False)
    completed_stages_json = Column(Text, nullable=True)
    progress_percent = Column(Integer, default=0, nullable=False)

    page_count = Column(Integer, default=0, nullable=False)
    ocr_required = Column(Boolean, default=False, nullable=False)
    detected_contract_type = Column(String(64), nullable=True)
    overall_risk_score = Column(Float, nullable=True)
    overall_risk_level = Column(String(32), nullable=True)
    executive_summary = Column(Text, nullable=True)
    missing_clauses_json = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    analysis_mode = Column(String(32), nullable=True)
    gemini_status = Column(String(32), nullable=True)
    fallback_used = Column(Boolean, default=False, nullable=False)
    fallback_reason = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
    embedding_backend = Column(String(64), nullable=True)

    owner = relationship("User", back_populates="documents")
    clauses = relationship(
        "Clause", back_populates="document", cascade="all, delete-orphan"
    )
    risk_assessments = relationship(
        "RiskAssessment", back_populates="document", cascade="all, delete-orphan"
    )
    comparisons = relationship(
        "Comparison", back_populates="document", cascade="all, delete-orphan"
    )
    reports = relationship(
        "AnalysisReport", back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_tenant_document", "tenant_id", "document_id"),
    )


class Clause(Base):
    __tablename__ = "clauses"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        String(32),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clause_id = Column(String(32), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False)
    description = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    classification_source = Column(String(32), nullable=True)
    original_text = Column(Text, nullable=False)
    page_number = Column(Integer, nullable=True)
    end_page_number = Column(Integer, nullable=True)
    location_type = Column(String(32), default="pdf_page", nullable=False)
    paragraph_index = Column(Integer, nullable=True)
    section_title = Column(String(255), nullable=True)
    segmentation_confidence = Column(String(16), default="high", nullable=False)
    segmentation_uncertain = Column(Boolean, default=False, nullable=False)

    document = relationship("Document", back_populates="clauses")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        String(32),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clause_id = Column(String(32), nullable=False, index=True)
    risk_level = Column(String(32), nullable=False)
    risk_score = Column(Float, nullable=True)
    risk_title = Column(String(255), nullable=True)
    explanation = Column(Text, nullable=False)
    potential_impact = Column(Text, nullable=True)
    suggested_action = Column(Text, nullable=True)
    page_number = Column(Integer, nullable=True)
    location_type = Column(String(32), default="pdf_page", nullable=False)
    paragraph_index = Column(Integer, nullable=True)
    section_title = Column(String(255), nullable=True)
    verified = Column(Boolean, default=True, nullable=False)
    finding_type = Column(String(32), default="detected_risk", nullable=False)

    document = relationship("Document", back_populates="risk_assessments")


class Comparison(Base):
    __tablename__ = "comparisons"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        String(32),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clause_id = Column(String(32), nullable=False, index=True)
    reference_text = Column(Text, nullable=False)
    differences = Column(Text, nullable=False)
    potential_implications = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)
    reference_source = Column(String(255), nullable=False)
    similarity_score = Column(Float, nullable=True)
    insufficient_evidence = Column(Boolean, default=False, nullable=False)
    verified = Column(Boolean, default=True, nullable=False)

    document = relationship("Document", back_populates="comparisons")


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        String(32),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_path = Column(String(512), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    document = relationship("Document", back_populates="reports")

