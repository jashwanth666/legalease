"""Sentence-Transformers embedding service with deterministic offline hashing fallback."""

import hashlib
import logging
import os
from pathlib import Path
import re

import numpy as np
from langchain_core.embeddings import Embeddings

from backend.config import get_settings


logger = logging.getLogger(__name__)


class DeterministicHashEmbeddings(Embeddings):
    """Offline deterministic 384-dim n-gram hashing embedder for environments without HF cache."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _embed_one(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        if not tokens:
            return vec.tolist()

        features = list(tokens)
        features.extend(f"{tokens[i]}_{tokens[i + 1]}" for i in range(len(tokens) - 1))
        for tok in tokens:
            if len(tok) >= 4:
                features.extend(tok[i : i + 4] for i in range(len(tok) - 3))

        for feat in features:
            digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[idx] += sign

        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


class EmbeddingService(Embeddings):
    """Loads SentenceTransformers (preferring local cache) with seamless fallback."""

    def __init__(self, model_name: str | None = None, allow_download: bool = False) -> None:
        settings = get_settings()
        self.model_name = model_name or settings.embedding_model
        self.allow_download = allow_download
        self._model = None
        self._backend_name = "uninitialized"
        self._fallback = DeterministicHashEmbeddings(dim=384)

    def _is_model_cached(self) -> bool:
        model_path = Path(self.model_name)
        if model_path.exists():
            return True
        repo_id = (
            self.model_name
            if "/" in self.model_name
            else f"sentence-transformers/{self.model_name}"
        )
        hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
        hub_dir = hf_home / "hub"
        target = hub_dir / f"models--{repo_id.replace('/', '--')}"
        return target.exists()

    def _ensure_model(self) -> None:
        if self._backend_name != "uninitialized":
            return

        if not self.allow_download and not self._is_model_cached():
            self._model = None
            self._backend_name = "deterministic_hash"
            return

        try:
            from sentence_transformers import SentenceTransformer

            try:
                self._model = SentenceTransformer(self.model_name, local_files_only=True)
                self._backend_name = "sentence_transformers"
                return
            except Exception:
                if self.allow_download:
                    self._model = SentenceTransformer(self.model_name)
                    self._backend_name = "sentence_transformers"
                    return
        except Exception as exc:
            logger.info("SentenceTransformer unavailable (%s); using deterministic hash embeddings", exc)

        self._model = None
        self._backend_name = "deterministic_hash"

    @property
    def backend_name(self) -> str:
        self._ensure_model()
        return self._backend_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._ensure_model()
        if not texts:
            return []
        if self._model is not None:
            vectors = self._model.encode(texts, normalize_embeddings=True)
            return vectors.tolist()
        return self._fallback.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        self._ensure_model()
        if self._model is not None:
            vec = self._model.encode([text], normalize_embeddings=True)[0]
            return vec.tolist()
        return self._fallback.embed_query(text)
