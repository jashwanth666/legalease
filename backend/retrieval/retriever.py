"""LangChain-compatible retriever wrapping LegalEase's FAISS reference store."""

from pathlib import Path
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document as LCDocument
from langchain_core.retrievers import BaseRetriever
from pydantic import Field

from backend.config import get_settings
from backend.retrieval.embeddings import EmbeddingService
from backend.retrieval.vectorstore import ReferenceVectorStore


class TemplateLangChainRetriever(BaseRetriever):
    """LangChain BaseRetriever returning reference clause Documents with metadata."""

    vectorstore: Any = Field(...)
    top_k: int = 3
    contract_type: str | None = None
    category: str | None = None

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[LCDocument]:
        matches = self.vectorstore.search(
            query=query,
            top_k=self.top_k,
            contract_type=self.contract_type,
            category=self.category,
        )
        return [
            LCDocument(
                page_content=m["text"],
                metadata={
                    "reference_id": m["reference_id"],
                    "contract_type": m["contract_type"],
                    "category": m["category"],
                    "title": m["title"],
                    "reference_source": m["reference_source"],
                    "jurisdiction": m["jurisdiction"],
                    "illustrative_notice": m["illustrative_notice"],
                    "similarity_score": m["similarity_score"],
                },
            )
            for m in matches
        ]


class TemplateRetriever:
    """High-level facade for indexing and retrieving reference contract clauses."""

    def __init__(
        self,
        vectorstore_dir: Path | None = None,
        templates_dir: Path | None = None,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        settings = get_settings()
        self.store = ReferenceVectorStore(
            vectorstore_dir=vectorstore_dir or settings.vectorstore_dir,
            templates_dir=templates_dir or settings.reference_templates_dir,
            embedding_service=embedding_service or EmbeddingService(),
        )

    def rebuild(self) -> int:
        return self.store.build_index()

    def retrieve_for_clause(
        self,
        clause_text: str,
        category: str | None = None,
        contract_type: str | None = None,
        top_k: int = 2,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant reference clauses via the LangChain BaseRetriever."""
        lc_retriever = TemplateLangChainRetriever(
            vectorstore=self.store,
            top_k=top_k,
            contract_type=contract_type,
            category=category,
        )
        docs = lc_retriever.invoke(clause_text)
        return [
            {
                "text": doc.page_content,
                **doc.metadata,
            }
            for doc in docs
        ]

