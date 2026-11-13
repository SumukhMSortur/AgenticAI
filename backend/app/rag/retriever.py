"""Hybrid BM25 + dense retriever with cross-encoder reranking for compliance RAG."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from math import isfinite
from typing import Any, Literal, Protocol

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from backend.app.core.logging import get_logger
from backend.app.rag.models import RERANKER_MODEL_NAME
from backend.app.rag.store import IVectorStore

logger = get_logger(__name__)

RetrievalMode = Literal["bm25", "dense", "hybrid", "hybrid_rerank"]


class PairScorer(Protocol):
    def predict(
        self,
        inputs: Sequence[tuple[str, str]],
        *,
        show_progress_bar: bool,
        convert_to_numpy: bool,
    ) -> Any: ...


class CrossEncoderReranker:
    """Score query/chunk pairs with a locally cached sentence-transformers cross-encoder."""

    def __init__(
        self,
        model_name: str = RERANKER_MODEL_NAME,
        device: str = "cpu",
        model: PairScorer | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self._model = model

    def _get_model(self) -> PairScorer:
        if self._model is None:
            self._model = CrossEncoder(
                self.model_name,
                device=self.device,
                local_files_only=True,
            )
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []

        pairs = [(query, str(candidate["text"])) for candidate in candidates]
        raw_scores = self._get_model().predict(
            pairs,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        scores = np.asarray(raw_scores, dtype=float).reshape(-1).tolist()
        if len(scores) != len(candidates) or not all(isfinite(score) for score in scores):
            raise RuntimeError("Cross-encoder returned an invalid score vector.")

        scored = [
            (score, str(candidate.get("chunk_id", "")), candidate)
            for score, candidate in zip(scores, candidates, strict=True)
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [{**candidate, "_cross_encoder_score": score} for score, _, candidate in scored]


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + lowercase tokenizer for BM25."""
    return text.lower().split()


class HybridRetriever:
    """Combines BM25 sparse retrieval with dense vector search, with optional reranking.

    Algorithm:
    1. BM25 retrieves top-k candidates from the in-memory corpus.
    2. Dense vector store retrieves top-k by cosine similarity.
    3. Results are merged via reciprocal rank fusion (RRF).
    4. A cross-encoder reranks the fused candidate set.
    """

    def __init__(
        self,
        vector_store: IVectorStore,
        corpus_chunks: list[dict[str, Any]] | None = None,
        reranker: CrossEncoderReranker | None = None,
    ) -> None:
        self._store = vector_store
        self._corpus: list[dict[str, Any]] = corpus_chunks or []
        self._reranker = reranker or CrossEncoderReranker()
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
        self._bm25 = None
        if self._corpus:
            self._build_bm25()

    def retrieve(
        self,
        query: str,
        assessment_date: date,
        jurisdiction: str | None = None,
        n_results: int = 5,
        bm25_weight: float = 0.3,
        dense_weight: float = 0.7,
        mode: RetrievalMode = "hybrid_rerank",
    ) -> list[dict[str, Any]]:
        """Run the selected sparse, dense, hybrid, or reranked retrieval path."""
        if not query.strip():
            raise ValueError("query must not be empty")
        if n_results < 1:
            raise ValueError("n_results must be positive")
        if mode not in {"bm25", "dense", "hybrid", "hybrid_rerank"}:
            raise ValueError(f"unsupported retrieval mode: {mode}")
        if bm25_weight < 0 or dense_weight < 0 or bm25_weight + dense_weight <= 0:
            raise ValueError("retrieval weights must be non-negative and not both zero")

        candidate_count = n_results * 3

        # ---- BM25 pass ----
        bm25_results: list[dict[str, Any]] = []
        if self._bm25 and self._corpus:
            tokens = _tokenize(query)
            scores = self._bm25.get_scores(tokens)
            ranked_indices = sorted(
                range(len(scores)),
                key=lambda i: (-scores[i], str(self._corpus[i].get("chunk_id", ""))),
            )
            for rank, idx in enumerate(ranked_indices):
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
                if len(bm25_results) >= candidate_count:
                    break

        # ---- Dense pass ----
        dense_results = self._store.query(
            query_text=query,
            assessment_date=assessment_date,
            jurisdiction=jurisdiction,
            n_results=candidate_count,
        )
        for rank, r in enumerate(dense_results):
            r["_dense_rank"] = rank

        if mode == "bm25":
            return bm25_results[:n_results]
        if mode == "dense":
            return dense_results[:n_results]

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

        merged = sorted(rrf_scores.items(), key=lambda item: (-item[1], item[0]))
        candidates: list[dict[str, Any]] = []
        for cid, score in merged[:candidate_count]:
            chunk = chunk_by_id[cid].copy()
            chunk["_rrf_score"] = score
            candidates.append(chunk)

        if mode == "hybrid":
            return candidates[:n_results]
        return self._reranker.rerank(query, candidates)[:n_results]
