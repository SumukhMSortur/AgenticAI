"""Vector store interface and ChromaDB implementation with date-aware filtering."""

from __future__ import annotations

import hashlib
import os

# Ensure offline mode for transformers/huggingface in sandboxed environments
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, cast

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from backend.app.core.logging import get_logger
from backend.app.rag.chunker import RegulationChunk

logger = get_logger(__name__)

# Embedding model — fully offline, small, fast
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
COLLECTION_NAME = "regulations"


class IVectorStore(ABC):
    """Abstract interface for a vector store over regulation chunks."""

    @abstractmethod
    def upsert_chunks(self, chunks: list[RegulationChunk]) -> None:
        """Add or update chunks in the store."""

    @abstractmethod
    def query(
        self,
        query_text: str,
        assessment_date: date,
        jurisdiction: str | None = None,
        n_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Return top-n chunks valid on assessment_date, excluding superseded ones."""

    @abstractmethod
    def count(self) -> int:
        """Return total number of chunks stored."""

    @abstractmethod
    def reset(self) -> None:
        """Clear all data (for testing)."""


class ChromaVectorStore(IVectorStore):
    """Persistent ChromaDB-backed vector store with sentence-transformer embeddings.

    Filtering logic:
    - Only return chunks where effective_from <= assessment_date (regulation in force).
    - Exclude chunks where superseded_by is NOT None AND superseded_by <= assessment_date
      (regulation has been replaced by the assessment date).
    """

    def __init__(
        self,
        persist_dir: str = ".chroma",
        embed_model: str = EMBED_MODEL_NAME,
        in_memory: bool = False,
    ) -> None:
        if in_memory:
            self._client = chromadb.Client()
        else:
            self._client = chromadb.PersistentClient(
                path=persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"Loading embedding model: {embed_model}")
        self._embedder: SentenceTransformer = SentenceTransformer(embed_model)
        logger.info("Embedding model ready.")

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.encode(texts, show_progress_bar=False).tolist()  # type: ignore[no-any-return]

    def upsert_chunks(self, chunks: list[RegulationChunk]) -> None:
        """Embed and upsert regulation chunks."""
        if not chunks:
            return

        ids = [c.chunk_id for c in chunks]
        texts = [c.text for c in chunks]
        embeddings = self._embed(texts)

        metadatas = [
            {
                "regulation_id": c.regulation_id,
                "version_id": c.version_id,
                "jurisdiction": c.jurisdiction,
                "effective_from": c.effective_from.isoformat(),
                "superseded_by": c.superseded_by or "",
                "section_type": c.section_type,
                "section_number": c.section_number,
                "chunk_id": c.chunk_id,
            }
            for c in chunks
        ]

        self._collection.upsert(
            ids=ids,
            embeddings=cast(Any, embeddings),
            documents=texts,
            metadatas=cast(Any, metadatas),
        )
        logger.info(f"Upserted {len(chunks)} regulation chunks.")

    def query(
        self,
        query_text: str,
        assessment_date: date,
        jurisdiction: str | None = None,
        n_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Dense vector search with date-aware filtering applied post-retrieval.

        ChromaDB's metadata filtering does not support date comparisons natively,
        so we over-fetch and filter in Python.
        """
        query_embedding = self._embed([query_text])[0]
        assessment_iso = assessment_date.isoformat()

        # Over-fetch to allow for post-retrieval date filtering
        fetch_n = min(n_results * 5, self.count())
        if fetch_n == 0:
            return []

        results = self._collection.query(
            query_embeddings=cast(Any, [query_embedding]),
            n_results=fetch_n,
            include=["documents", "metadatas", "distances"],
        )

        filtered: list[dict[str, Any]] = []
        docs = results.get("documents") or [[]]
        metas = results.get("metadatas") or [[]]
        dists = results.get("distances") or [[]]

        for doc, meta, dist in zip(docs[0], metas[0], dists[0], strict=False):
            meta_dict = cast(dict[str, Any], meta) if meta else {}
            # Filter: regulation must be in force by assessment_date
            eff_from = str(meta_dict.get("effective_from", ""))
            if eff_from and eff_from > assessment_iso:
                continue  # Not yet in force

            # Filter: exclude superseded regulations
            sup_by = str(meta_dict.get("superseded_by", ""))
            if sup_by and sup_by <= assessment_iso:
                continue  # Superseded by the assessment date

            # Filter by jurisdiction if requested
            if jurisdiction and meta_dict.get("jurisdiction", "") != jurisdiction:
                continue

            filtered.append(
                {
                    "chunk_id": meta_dict.get("chunk_id", ""),
                    "text": doc,
                    "score": float(1.0 - dist),  # cosine similarity
                    "regulation_id": meta_dict.get("regulation_id", ""),
                    "version_id": meta_dict.get("version_id", ""),
                    "jurisdiction": meta_dict.get("jurisdiction", ""),
                    "effective_from": eff_from,
                    "superseded_by": sup_by,
                    "section_type": meta_dict.get("section_type", ""),
                    "section_number": meta_dict.get("section_number", ""),
                }
            )

            if len(filtered) >= n_results:
                break

        return filtered

    def count(self) -> int:
        return self._collection.count()

    def reset(self) -> None:
        """Delete and recreate the collection (for testing)."""
        self._client.delete_collection(COLLECTION_NAME)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )


def _stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]
