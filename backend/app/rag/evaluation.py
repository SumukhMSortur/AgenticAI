"""Reproducible citation and Ragas evaluation helpers for the regulation retriever."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite
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


@dataclass(frozen=True)
class NoSupportQuery:
    query_id: str
    query: str
    assessment_date: date
    jurisdiction: str


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
        retrieved = [str(chunk.get("chunk_id", "")) for chunk in case.retrieved_chunks[:k]]
        hits = expected.intersection(retrieved)
        precision_scores.append(len(hits) / k)
        recall_scores.append(len(hits) / len(expected))
        reciprocal_ranks.append(
            next(
                (1.0 / rank for rank, chunk_id in enumerate(retrieved, 1) if chunk_id in expected),
                0.0,
            )
        )

    return {
        "queries": len(cases),
        "k": k,
        "citation_precision_at_k": sum(precision_scores) / len(precision_scores),
        "citation_recall_at_k": sum(recall_scores) / len(recall_scores),
        "mean_reciprocal_rank_at_k": sum(reciprocal_ranks) / len(reciprocal_ranks),
    }


def load_no_support_queries(path: Path, minimum_queries: int = 1) -> list[NoSupportQuery]:
    """Load queries whose answers are deliberately absent from the indexed corpus."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
        raise ValueError("No-support set must contain a 'queries' array.")

    queries: list[NoSupportQuery] = []
    seen_ids: set[str] = set()
    for row in data["queries"]:
        if not isinstance(row, dict):
            raise ValueError("Each no-support query must be an object.")
        query_id = _required_string(row, "query_id")
        if query_id in seen_ids:
            raise ValueError(f"Duplicate no-support query ID: {query_id}")
        seen_ids.add(query_id)
        queries.append(
            NoSupportQuery(
                query_id=query_id,
                query=_required_string(row, "query"),
                assessment_date=date.fromisoformat(_required_string(row, "assessment_date")),
                jurisdiction=_required_string(row, "jurisdiction"),
            )
        )

    if len(queries) < minimum_queries:
        raise ValueError(
            f"No-support set has {len(queries)} queries; at least {minimum_queries} are required."
        )
    return queries


def answerability_metrics(
    supported_scores: Sequence[tuple[str, float | None]],
    unsupported_scores: Sequence[tuple[str, float | None]],
    support_threshold: float,
) -> dict[str, object]:
    """Measure reranker-threshold support decisions on labeled answerable/unanswerable queries."""
    if not isfinite(support_threshold):
        raise ValueError("support_threshold must be finite")
    if not supported_scores or not unsupported_scores:
        raise ValueError("Supported and no-support query sets must both be non-empty.")

    per_query: list[dict[str, object]] = []
    supported_correct = 0
    unsupported_correct = 0
    for expected_answerable, rows in (
        (True, supported_scores),
        (False, unsupported_scores),
    ):
        for query_id, score in rows:
            if score is not None and not isfinite(score):
                raise ValueError(f"Query '{query_id}' has a non-finite support score.")
            predicted_answerable = score is not None and score >= support_threshold
            correct = predicted_answerable == expected_answerable
            if expected_answerable:
                supported_correct += int(correct)
            else:
                unsupported_correct += int(correct)
            per_query.append(
                {
                    "query_id": query_id,
                    "expected_answerable": expected_answerable,
                    "predicted_answerable": predicted_answerable,
                    "max_cross_encoder_score": score,
                    "correct": correct,
                }
            )

    supported_count = len(supported_scores)
    unsupported_count = len(unsupported_scores)
    supported_recall = supported_correct / supported_count
    no_support_accuracy = unsupported_correct / unsupported_count
    total_accuracy = (supported_correct + unsupported_correct) / (
        supported_count + unsupported_count
    )
    return {
        "support_threshold": support_threshold,
        "supported_queries": supported_count,
        "supported_query_recall": supported_recall,
        "no_support_queries": unsupported_count,
        "no_support_accuracy": no_support_accuracy,
        "total_queries": supported_count + unsupported_count,
        "accuracy": total_accuracy,
        "balanced_accuracy": (supported_recall + no_support_accuracy) / 2,
        "per_query": per_query,
    }


def count_date_filter_violations(cases: Sequence[RAGEvaluationCase]) -> int:
    """Count returned passages that are future-effective or already superseded."""
    violations = 0
    for case in cases:
        assessment_date = case.golden_query.assessment_date.isoformat()
        for chunk in case.retrieved_chunks:
            effective_from = chunk.get("effective_from")
            superseded_by = chunk.get("superseded_by")
            if isinstance(effective_from, str) and effective_from > assessment_date:
                violations += 1
            if (
                isinstance(superseded_by, str)
                and superseded_by
                and superseded_by <= assessment_date
            ):
                violations += 1
    return violations


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
