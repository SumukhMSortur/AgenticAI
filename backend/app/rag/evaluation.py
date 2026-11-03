"""Reproducible citation and Ragas evaluation helpers for the regulation retriever."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class GoldenQuery:
    query_id: str
    query: str
    assessment_date: date
    jurisdiction: str
    expected_chunk_ids: tuple[str, ...]
    reference_answer: str


@dataclass(frozen=True)
class RAGEvaluationCase:
    golden_query: GoldenQuery
    retrieved_chunks: tuple[dict[str, object], ...]
    response: str = ""


class RagasScorer(Protocol):
    async def score(
        self,
        query: str,
        response: str,
        retrieved_contexts: list[str],
    ) -> tuple[float, float]: ...


def load_golden_queries(path: Path, minimum_queries: int = 60) -> list[GoldenQuery]:
    """Load and validate a labeled, date-aware retrieval set."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
        raise ValueError("Golden retrieval set must contain a 'queries' array.")

    queries: list[GoldenQuery] = []
    seen_ids: set[str] = set()
    for row in data["queries"]:
        if not isinstance(row, dict):
            raise ValueError("Each golden retrieval query must be an object.")
        query_id = _required_string(row, "query_id")
        query = _required_string(row, "query")
        jurisdiction = _required_string(row, "jurisdiction")
        reference_answer = _required_string(row, "reference_answer")
        raw_date = _required_string(row, "assessment_date")
        raw_expected_ids = row.get("expected_chunk_ids")
        if query_id in seen_ids:
            raise ValueError(f"Duplicate golden query ID: {query_id}")
        if (
            not isinstance(raw_expected_ids, list)
            or not raw_expected_ids
            or not all(isinstance(item, str) and item.strip() for item in raw_expected_ids)
        ):
            raise ValueError(f"Golden query '{query_id}' must have expected chunk IDs.")
        seen_ids.add(query_id)
        queries.append(
            GoldenQuery(
                query_id=query_id,
                query=query,
                assessment_date=date.fromisoformat(raw_date),
                jurisdiction=jurisdiction,
                expected_chunk_ids=tuple(raw_expected_ids),
                reference_answer=reference_answer,
            )
        )

    if len(queries) < minimum_queries:
        raise ValueError(
            f"Golden retrieval set has {len(queries)} queries; at least {minimum_queries} are required."
        )
    return queries


def citation_metrics(
    cases: Sequence[RAGEvaluationCase],
    k: int = 5,
) -> dict[str, float | int]:
    """Compute macro precision@k, recall@k, and reciprocal rank on labeled chunk IDs."""
    if k < 1:
        raise ValueError("k must be positive.")
    if not cases:
        raise ValueError("At least one retrieval case is required.")

    precision_scores: list[float] = []
    recall_scores: list[float] = []
    reciprocal_ranks: list[float] = []

    for case in cases:
        expected = set(case.golden_query.expected_chunk_ids)
        retrieved = [
            str(chunk.get("chunk_id", ""))
            for chunk in case.retrieved_chunks[:k]
        ]
        hits = expected.intersection(retrieved)
        precision_scores.append(len(hits) / k)
        recall_scores.append(len(hits) / len(expected))
        reciprocal_ranks.append(
            next((1.0 / rank for rank, chunk_id in enumerate(retrieved, 1) if chunk_id in expected), 0.0)
        )

    return {
        "queries": len(cases),
        "k": k,
        "citation_precision_at_k": sum(precision_scores) / len(precision_scores),
        "citation_recall_at_k": sum(recall_scores) / len(recall_scores),
        "mean_reciprocal_rank_at_k": sum(reciprocal_ranks) / len(reciprocal_ranks),
    }


async def evaluate_ragas(
    cases: Sequence[RAGEvaluationCase],
    scorer: RagasScorer,
) -> dict[str, object]:
    """Score each response with an injected Ragas judge and aggregate the metrics."""
    if not cases:
        raise ValueError("At least one RAG evaluation case is required.")

    per_query: list[dict[str, str | float]] = []
    faithfulness_scores: list[float] = []
    answer_relevance_scores: list[float] = []
    for case in cases:
        if not case.response.strip():
            raise ValueError(f"Query '{case.golden_query.query_id}' has no response to evaluate.")
        contexts = [
            str(chunk["text"])
            for chunk in case.retrieved_chunks
            if isinstance(chunk.get("text"), str)
        ]
        if not contexts:
            raise ValueError(
                f"Query '{case.golden_query.query_id}' has no retrieved context to evaluate."
            )

        faithfulness, answer_relevance = await scorer.score(
            case.golden_query.query,
            case.response,
            contexts,
        )
        _validate_score("faithfulness", faithfulness, case.golden_query.query_id)
        _validate_score("answer_relevance", answer_relevance, case.golden_query.query_id)
        faithfulness_scores.append(faithfulness)
        answer_relevance_scores.append(answer_relevance)
        per_query.append(
            {
                "query_id": case.golden_query.query_id,
                "faithfulness": faithfulness,
                "answer_relevance": answer_relevance,
            }
        )

    return {
        "faithfulness": sum(faithfulness_scores) / len(faithfulness_scores),
        "answer_relevance": sum(answer_relevance_scores) / len(answer_relevance_scores),
        "per_query": per_query,
    }


def _required_string(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Golden retrieval query requires a non-empty '{key}'.")
    return value


def _validate_score(metric: str, score: float, query_id: str) -> None:
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
        raise ValueError(f"Invalid {metric} score for query '{query_id}': {score!r}")
