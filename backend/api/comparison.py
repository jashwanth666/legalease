"""RAG reference template comparison endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.database import Clause, Comparison, Document, get_db
from backend.ingestion.template_loader import ILLUSTRATIVE_DEFAULT_NOTICE
from backend.retrieval.embeddings import EmbeddingService
from backend.retrieval.retriever import TemplateRetriever


router = APIRouter(prefix="/api", tags=["Comparison"])


@router.get("/compare/{document_id}")
def get_comparisons(document_id: str, db: Session = Depends(get_db)):
    """Return side-by-side uploaded clauses vs retrieved illustrative reference templates."""
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    if doc.processing_status != "analyzed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document '{document_id}' has not been analyzed yet.",
        )

    clauses = {
        c.clause_id: c
        for c in db.query(Clause).filter(Clause.document_id == document_id).all()
    }
    comparisons = (
        db.query(Comparison)
        .filter(Comparison.document_id == document_id)
        .order_by(Comparison.clause_id.asc())
        .all()
    )

    items = []
    for comp in comparisons:
        clause = clauses.get(comp.clause_id)
        try:
            diffs = json.loads(comp.differences)
            if not isinstance(diffs, list):
                diffs = [str(diffs)]
        except json.JSONDecodeError:
            diffs = [comp.differences]

        items.append(
            {
                "clause_id": comp.clause_id,
                "clause_title": clause.title if clause else comp.clause_id,
                "category": clause.category if clause else "Other",
                "page_number": clause.page_number if clause else None,
                "location_type": clause.location_type if clause else "pdf_page",
                "paragraph_index": clause.paragraph_index if clause else None,
                "section_title": clause.section_title if clause else None,
                "uploaded_clause": clause.original_text if clause else "",
                "reference_clause": comp.reference_text,
                "differences": diffs,
                "potential_implications": comp.potential_implications or "",
                "recommendation": comp.recommendation or "",
                "reference_source": comp.reference_source,
                "similarity_score": comp.similarity_score,
                "insufficient_evidence": bool(comp.insufficient_evidence),
                "verified": comp.verified,
                "illustrative_notice": ILLUSTRATIVE_DEFAULT_NOTICE,
            }
        )

    return {
        "document_id": document_id,
        "filename": doc.filename,
        "detected_contract_type": doc.detected_contract_type,
        "illustrative_notice": ILLUSTRATIVE_DEFAULT_NOTICE,
        "count": len(items),
        "comparisons": items,
    }


@router.post("/templates/rebuild")
def rebuild_reference_index(settings: Settings = Depends(get_settings)):
    """Rebuild the FAISS reference template vector store."""
    retriever = TemplateRetriever(
        vectorstore_dir=settings.vectorstore_dir,
        templates_dir=settings.reference_templates_dir,
        embedding_service=EmbeddingService(allow_download=False),
    )
    indexed_count = retriever.rebuild()
    meta = retriever.store.metadata
    return {
        "status": "ok",
        "indexed_clauses": indexed_count,
        "embedding_backend": retriever.store.embedding_service.backend_name,
        "embedding_model": retriever.store.embedding_service.model_name,
        "embedding_dimension": meta.get("embedding_dimension", retriever.store.embedding_service.embedding_dimension),
        "is_semantic_embeddings": retriever.store.embedding_service.is_semantic,
        "embedding_label": retriever.store.embedding_service.embedding_label,
        "template_hash": meta.get("template_hash"),
        "template_version": meta.get("template_version"),
    }

