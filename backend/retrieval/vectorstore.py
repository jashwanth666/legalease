"""FAISS vector store management for reference legal clauses."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from backend.ingestion.template_loader import ReferenceClause, load_reference_clauses
from backend.retrieval.embeddings import EmbeddingService


TEMPLATE_VERSION = "v1"


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
        self.metadata: dict[str, Any] = {}

    def _compute_templates_hash(self) -> str:
        """Compute deterministic SHA-256 over all template files in templates_dir."""
        digest = hashlib.sha256()
        if not self.templates_dir.exists():
            return digest.hexdigest()
        files = sorted(
            p for p in self.templates_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in {".txt", ".md"}
        )
        for path in files:
            rel = path.relative_to(self.templates_dir).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(path.read_bytes())
            digest.update(b"\x00")
        return digest.hexdigest()

    def build_index(self) -> int:
        """Load reference templates, embed clauses, and build + persist FAISS index."""
        clauses: list[ReferenceClause] = load_reference_clauses(self.templates_dir)
        self.vectorstore_dir.mkdir(parents=True, exist_ok=True)
        template_hash = self._compute_templates_hash()

        if not clauses:
            self.index = None
            self.records = []
            self.metadata = {}
            return 0

        texts = [
            f"{c.contract_type} | {c.category} | {c.title}\n{c.text}"
            for c in clauses
        ]
        vectors = np.array(self.embedding_service.embed_documents(texts), dtype=np.float32)
        faiss.normalize_L2(vectors)

        dim = int(vectors.shape[1])
        index = faiss.IndexFlatIP(dim)
        index.add(vectors)

        self.index = index
        self.records = [asdict(c) for c in clauses]
        self.metadata = {
            "embedding_backend": self.embedding_service.backend_name,
            "embedding_model": self.embedding_service.model_name,
            "embedding_dimension": dim,
            "is_semantic_embeddings": self.embedding_service.is_semantic,
            "embedding_label": self.embedding_service.embedding_label,
            "template_version": TEMPLATE_VERSION,
            "template_hash": template_hash,
            "count": len(self.records),
        }

        faiss.write_index(self.index, str(self.index_path))
        self.meta_path.write_text(
            json.dumps(
                {
                    **self.metadata,
                    "records": self.records,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return len(self.records)

    def ensure_loaded(self) -> None:
        """Load existing FAISS index if valid and fresh, else rebuild from templates."""
        current_hash = self._compute_templates_hash()
        current_backend = self.embedding_service.backend_name
        current_model = self.embedding_service.model_name
        current_dim = self.embedding_service.embedding_dimension

        if (
            self.index is not None
            and self.records
            and self.metadata.get("template_hash") == current_hash
            and self.metadata.get("embedding_backend") == current_backend
            and self.metadata.get("embedding_model") == current_model
            and self.metadata.get("embedding_dimension") == current_dim
        ):
            return

        if self.index_path.exists() and self.meta_path.exists():
            try:
                meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
                matches_meta = (
                    meta.get("embedding_backend") == current_backend
                    and meta.get("embedding_model") == current_model
                    and meta.get("embedding_dimension") == current_dim
                    and meta.get("template_version") == TEMPLATE_VERSION
                    and meta.get("template_hash") == current_hash
                )
                if matches_meta:
                    loaded_index = faiss.read_index(str(self.index_path))
                    if int(loaded_index.d) == current_dim and loaded_index.ntotal == len(meta.get("records", [])):
                        self.index = loaded_index
                        self.records = meta.get("records", [])
                        self.metadata = {k: v for k, v in meta.items() if k != "records"}
                        return
            except Exception:
                pass

        self.build_index()

    def search(
        self,
        query: str,
        top_k: int = 3,
        contract_type: str | None = None,
        category: str | None = None,
        min_similarity: float = 0.05,
    ) -> list[dict[str, Any]]:
        """Retrieve top-k similar reference clauses with metadata filtering."""
        self.ensure_loaded()
        if self.index is None or not self.records:
            return []

        query_vec = np.array([self.embedding_service.embed_query(query)], dtype=np.float32)
        if int(query_vec.shape[1]) != int(self.index.d):
            self.build_index()
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

