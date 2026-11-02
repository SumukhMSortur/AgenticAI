"""Hybrid BM25 + dense retriever with cross-encoder reranking for compliance RAG."""

from __future__ import annotations

from datetime import date
from typing import Any

from rank_bm25 import BM25Okapi

from backend.app.core.logging import get_logger
from backend.app.rag.store import IVectorStore

logger = get_logger(__name__)


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + lowercase tokenizer for BM25."""
    return text.lower().split()


class HybridRetriever:
    """Combines BM25 sparse retrieval with dense vector search, with optional reranking.

    Algorithm:
    1. BM25 retrieves top-k candidates from the in-memory corpus.
    2. Dense vector store retrieves top-k by cosine similarity.
    3. Results are merged via reciprocal rank fusion (RRF).
    4. Optional cross-encoder reranking (stub — returns merged ranking).
    """

    def __init__(
        self,
        vector_store: IVectorStore,
        corpus_chunks: list[dict[str, Any]] | None = None,
    ) -> None:
        self._store = vector_store
        self._corpus: list[dict[str, Any]] = corpus_chunks or []
        self._bm25: BM25Okapi | None = None
        if self._corpus:
            self._build_bm25()

    def _build_bm25(self) -> None:
        """Build the BM25 index from the in-memory corpus."""
        tokenized = [_tokenize(doc["text"]) for doc in self._corpus]
        self._bm25 = BM25Okapi(tokenized)
        logger.info(f"BM25 index built on {len(self._corpus)} chunks.")

    def load_corpus(self, chunks: list[dict[str, Any]]) -> None:
        """Load/replace the BM25 corpus."""
        self._corpus = chunks
        self._build_bm25()

    def retrieve(
        self,
        query: str,
        assessment_date: date,
        jurisdiction: str | None = None,
        n_results: int = 5,
        bm25_weight: float = 0.3,
        dense_weight: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Run hybrid retrieval and return top-n merged results."""
        # ---- BM25 pass ----
        bm25_results: list[dict[str, Any]] = []
        if self._bm25 and self._corpus:
            tokens = _tokenize(query)
            scores = self._bm25.get_scores(tokens)
            ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            for rank, idx in enumerate(ranked_indices[:n_results * 3]):
                chunk = self._corpus[idx]
                # Apply date filter
                eff_from = chunk.get("effective_from", "")
                sup_by = chunk.get("superseded_by", "")
                assessment_iso = assessment_date.isoformat()
                if eff_from and eff_from > assessment_iso:
                    continue
                if sup_by and sup_by <= assessment_iso:
                    continue
                if jurisdiction and chunk.get("jurisdiction", "") != jurisdiction:
                    continue
                bm25_results.append(
                    {**chunk, "_bm25_rank": rank, "_bm25_score": float(scores[idx])}
                )

        # ---- Dense pass ----
        dense_results = self._store.query(
            query_text=query,
            assessment_date=assessment_date,
            jurisdiction=jurisdiction,
            n_results=n_results * 3,
        )
        for rank, r in enumerate(dense_results):
            r["_dense_rank"] = rank

        # ---- RRF merge ----
        rrf_k = 60
        rrf_scores: dict[str, float] = {}
        chunk_by_id: dict[str, dict[str, Any]] = {}

        for rank, chunk in enumerate(bm25_results):
            cid = chunk.get("chunk_id", str(rank))
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + bm25_weight / (rrf_k + rank + 1)
            chunk_by_id[cid] = chunk

        for rank, chunk in enumerate(dense_results):
            cid = chunk.get("chunk_id", str(rank))
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + dense_weight / (rrf_k + rank + 1)
            if cid not in chunk_by_id:
                chunk_by_id[cid] = chunk

        merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        top_results: list[dict[str, Any]] = []
        for cid, score in merged[:n_results]:
            chunk = chunk_by_id[cid].copy()
            chunk["_rrf_score"] = score
            top_results.append(chunk)

        return top_results
