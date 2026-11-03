"""Local-only regulation retrieval service for API queries."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.core.config import settings
from backend.app.rag.chunker import chunk_regulations
from backend.app.rag.retriever import HybridRetriever
from backend.app.rag.store import ChromaVectorStore

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_REGULATIONS_PATH = _PROJECT_ROOT / "data" / "regulations" / "csddd_regulations.json"
_SUPPORT_THRESHOLD = -2.0


class RegulationQueryService:
    """Run date- and jurisdiction-filtered retrieval without an answer-generation call."""

    def __init__(self, store: ChromaVectorStore, retriever: HybridRetriever) -> None:
        self._store = store
        self._retriever = retriever

    @classmethod
    def load_local(cls) -> RegulationQueryService:
        store = get_regulation_vector_store()
        corpus = [
            {
                **asdict(chunk),
                "effective_from": chunk.effective_from.isoformat(),
                "superseded_by": chunk.superseded_by or "",
            }
            for chunk in chunk_regulations(_REGULATIONS_PATH)
        ]
        return cls(store, HybridRetriever(store, corpus))

    def query(
        self,
        query: str,
        assessment_date: date,
        jurisdiction: str,
        top_k: int,
    ) -> tuple[bool, list[dict[str, Any]]]:
        passages = self._retriever.retrieve(
            query=query,
            assessment_date=assessment_date,
            jurisdiction=jurisdiction,
            n_results=top_k,
            mode="hybrid_rerank",
        )
        if not passages:
            return False, []
        score = passages[0].get("_cross_encoder_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise RuntimeError("Cross-encoder result is missing a valid support score")
        if score < _SUPPORT_THRESHOLD:
            return False, []
        return True, [
            {
                "chunk_id": str(item["chunk_id"]),
                "text": str(item["text"]),
                "regulation_id": str(item["regulation_id"]),
                "version_id": str(item["version_id"]),
                "jurisdiction": str(item["jurisdiction"]),
                "section_number": str(item["section_number"]),
                "score": float(item["_cross_encoder_score"]),
            }
            for item in passages
        ]


@lru_cache(maxsize=1)
def get_regulation_vector_store() -> ChromaVectorStore:
    """Load the persistent local store and bootstrap the checked-in corpus once."""
    persist_dir = settings.CHROMA_PERSIST_DIRECTORY
    if not persist_dir.is_absolute():
        persist_dir = _PROJECT_ROOT / persist_dir
    store = ChromaVectorStore(persist_dir=str(persist_dir))
    if store.count() == 0:
        store.upsert_chunks(chunk_regulations(_REGULATIONS_PATH))
    return store


@lru_cache(maxsize=1)
def get_regulation_query_service() -> RegulationQueryService:
    """Reuse the local vector store and loaded models between API requests."""
    return RegulationQueryService.load_local()
