"""FAISS vector store management for reference legal clauses."""

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from backend.ingestion.template_loader import ReferenceClause, load_reference_clauses
from backend.retrieval.embeddings import EmbeddingService


class ReferenceVectorStore:
    """Persists and queries FAISS cosine-similarity index over reference clauses."""

    def __init__(
        self,
        vectorstore_dir: Path,
        templates_dir: Path,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.vectorstore_dir = vectorstore_dir
        self.templates_dir = templates_dir
        self.embedding_service = embedding_service or EmbeddingService()
        self.index_path = self.vectorstore_dir / "reference_clauses.faiss"
        self.meta_path = self.vectorstore_dir / "reference_clauses.json"
        self.index: faiss.IndexFlatIP | None = None
        self.records: list[dict[str, Any]] = []

    def build_index(self) -> int:
        """Load reference templates, embed clauses, and build + persist FAISS index."""
        clauses: list[ReferenceClause] = load_reference_clauses(self.templates_dir)
        self.vectorstore_dir.mkdir(parents=True, exist_ok=True)

        if not clauses:
            self.index = None
            self.records = []
            return 0

        texts = [
            f"{c.contract_type} | {c.category} | {c.title}\n{c.text}"
            for c in clauses
        ]
        vectors = np.array(self.embedding_service.embed_documents(texts), dtype=np.float32)
        faiss.normalize_L2(vectors)

        dim = vectors.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(vectors)

        self.index = index
        self.records = [asdict(c) for c in clauses]

        faiss.write_index(self.index, str(self.index_path))
        self.meta_path.write_text(
            json.dumps(
                {
                    "embedding_backend": self.embedding_service.backend_name,
                    "count": len(self.records),
                    "records": self.records,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return len(self.records)

    def ensure_loaded(self) -> None:
        """Load existing FAISS index from disk or build it from templates if missing."""
        if self.index is not None and self.records:
            return

        if self.index_path.exists() and self.meta_path.exists():
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            if meta.get("embedding_backend") == self.embedding_service.backend_name:
                self.index = faiss.read_index(str(self.index_path))
                self.records = meta.get("records", [])
                return

        self.build_index()

    def search(
        self,
        query: str,
        top_k: int = 3,
        contract_type: str | None = None,
        category: str | None = None,
        min_similarity: float = 0.05,
    ) -> list[dict[str, Any]]:
        """Retrieve top-k semantically similar reference clauses with metadata filtering."""
        self.ensure_loaded()
        if self.index is None or not self.records:
            return []

        query_vec = np.array([self.embedding_service.embed_query(query)], dtype=np.float32)
        faiss.normalize_L2(query_vec)

        search_k = min(len(self.records), max(top_k * 5, 15))
        scores, indices = self.index.search(query_vec, search_k)

        candidates: list[dict[str, Any]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.records):
                continue
            sim = float(score)
            if sim < min_similarity:
                continue

            rec = dict(self.records[idx])
            # Mild domain alignment boost when contract type or category matches
            boost = 0.0
            if contract_type and rec.get("contract_type", "").lower() == contract_type.lower():
                boost += 0.12
            if category and rec.get("category", "").lower() == category.lower():
                boost += 0.18

            rec["similarity_score"] = round(min(1.0, max(0.0, sim)), 4)
            rec["_rank_score"] = sim + boost
            candidates.append(rec)

        # Prevent comparing against arbitrary unrelated clauses when category doesn't match
        if category and category != "Other":
            cat_matches = [
                c for c in candidates if c.get("category", "").lower() == category.lower()
            ]
            if cat_matches:
                candidates = cat_matches

        candidates.sort(key=lambda item: item["_rank_score"], reverse=True)
        results = candidates[:top_k]
        for item in results:
            item.pop("_rank_score", None)
        return results

