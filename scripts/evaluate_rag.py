"""Run the labeled retrieval gate and, with explicit opt-in, Ragas model judging."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from backend.app.core.config import settings
from backend.app.integrations.gemini_rag import GeminiRAGAnswerer
from backend.app.integrations.openai_ragas import GuardedOpenAIRagasJudge
from backend.app.rag.chunker import chunk_regulations
from backend.app.rag.evaluation import (
    RAGEvaluationCase,
    citation_metrics,
    evaluate_ragas,
    load_golden_queries,
)
from backend.app.rag.models import EMBED_MODEL_NAME
from backend.app.rag.ragas_scorer import LocalRagasEmbedding, RagasMetricScorer
from backend.app.rag.retriever import CrossEncoderReranker, HybridRetriever
from backend.app.rag.store import ChromaVectorStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-external-model-calls",
        action="store_true",
        help="Permit guarded Gemini generation and OpenAI Ragas judging; may incur charges.",
    )
    args = parser.parse_args()

    config_path = REPOSITORY_ROOT / "config" / "rag.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    evaluation_config = config["evaluation"]
    retriever_config = config["retriever"]
    generator_config = evaluation_config["generator"]
    judge_config = evaluation_config["judge"]
    if generator_config["family"] == judge_config["family"]:
        raise ValueError("Ragas judge and response generator must use different model families.")

    golden_path = REPOSITORY_ROOT / evaluation_config["golden_set"]
    queries = load_golden_queries(
        golden_path,
        minimum_queries=int(evaluation_config["minimum_queries"]),
    )
    regulations_path = REPOSITORY_ROOT / "data" / "regulations" / "csddd_regulations.json"
    chunks = chunk_regulations(regulations_path)
    store = ChromaVectorStore(in_memory=True)
    store.reset()
    store.upsert_chunks(chunks)

    corpus = [
        {
            "chunk_id": chunk.chunk_id,
            "text": chunk.text,
            "regulation_id": chunk.regulation_id,
            "version_id": chunk.version_id,
            "parent_id": chunk.parent_id,
            "jurisdiction": chunk.jurisdiction,
            "effective_from": chunk.effective_from.isoformat(),
            "superseded_by": chunk.superseded_by or "",
            "section_type": chunk.section_type,
            "section_number": chunk.section_number,
        }
        for chunk in chunks
    ]
    retriever = HybridRetriever(
        vector_store=store,
        corpus_chunks=corpus,
        reranker=CrossEncoderReranker(
            model_name=str(retriever_config["reranker_model"]),
        ),
    )

    cases: list[RAGEvaluationCase] = []
    for query in queries:
        retrieved = retriever.retrieve(
            query=query.query,
            assessment_date=query.assessment_date,
            jurisdiction=query.jurisdiction,
            n_results=int(retriever_config["top_k"]),
        )
        cases.append(
            RAGEvaluationCase(
                golden_query=query,
                retrieved_chunks=tuple(retrieved),
            )
        )

    citation_results = citation_metrics(cases, k=int(retriever_config["top_k"]))
    report_path = REPOSITORY_ROOT / evaluation_config["report"]
    report: dict[str, Any] = {
        "report_version": "1.0.0",
        "status": "running_external_eval" if args.allow_external_model_calls else "pending_ragas_judge",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_git_sha": _source_git_sha(),
        "dataset_sha256": hashlib.sha256(golden_path.read_bytes()).hexdigest(),
        "query_count": len(queries),
        "corpus_chunk_count": len(chunks),
        "software": {
            "ragas": importlib.metadata.version("ragas"),
            "sentence_transformers": importlib.metadata.version("sentence-transformers"),
        },
        "models": {
            "embedding": EMBED_MODEL_NAME,
            "reranker": retriever_config["reranker_model"],
            "generator": {
                **generator_config,
                "model": settings.GEMINI_MODEL,
            },
            "judge": judge_config,
        },
        "evaluation_config": {
            "minimum_queries": int(evaluation_config["minimum_queries"]),
            "top_k": int(retriever_config["top_k"]),
            "thresholds": evaluation_config["gates"],
        },
        "external_model_calls_enabled": args.allow_external_model_calls,
        "citation_metrics": citation_results,
        "ragas_metrics": None,
        "gates": _citation_gates(
            citation_results,
            evaluation_config["gates"],
            len(queries),
            int(evaluation_config["minimum_queries"]),
        ),
        "per_query": [
            {
                "query_id": case.golden_query.query_id,
                "expected_chunk_ids": list(case.golden_query.expected_chunk_ids),
                "retrieved_chunk_ids": [
                    str(chunk.get("chunk_id", "")) for chunk in case.retrieved_chunks
                ],
            }
            for case in cases
        ],
    }
    _write_report(report_path, report)

    if not args.allow_external_model_calls:
        print(
            f"Retrieval metrics written to {report_path}; Ragas judging is pending explicit "
            "external-model opt-in."
        )
        return 2

    answerer = GeminiRAGAnswerer(
        tenant_id="rag-evaluation",
        tenant_opted_in=True,
    )
    cases = [
        RAGEvaluationCase(
            golden_query=case.golden_query,
            retrieved_chunks=case.retrieved_chunks,
            response=answerer(case.golden_query.query, case.retrieved_chunks),
        )
        for case in cases
    ]

    ragas_results = asyncio.run(_score_external(cases, judge_config))

    report["ragas_metrics"] = ragas_results
    report["gates"] = {
        "golden_query_count": len(queries)
        >= int(evaluation_config["minimum_queries"]),
        **_evaluate_gates(
            citation_results,
            ragas_results,
            evaluation_config["gates"],
        ),
    }
    report["status"] = "pass" if all(report["gates"].values()) else "failed"
    _write_report(report_path, report)
    print(f"RAG evaluation status: {report['status']} ({report_path})")
    return 0 if report["status"] == "pass" else 1


def _evaluate_gates(
    citation_results: dict[str, float | int],
    ragas_results: dict[str, object],
    thresholds: dict[str, float],
) -> dict[str, bool]:
    return {
        "citation_precision_at_5": float(citation_results["citation_precision_at_k"])
        >= thresholds["citation_precision_at_5"],
        "citation_recall_at_5": float(citation_results["citation_recall_at_k"])
        >= thresholds["citation_recall_at_5"],
        "faithfulness": _metric_value(ragas_results, "faithfulness")
        >= thresholds["faithfulness"],
        "answer_relevance": _metric_value(ragas_results, "answer_relevance")
        >= thresholds["answer_relevance"],
    }


def _citation_gates(
    citation_results: dict[str, float | int],
    thresholds: dict[str, float],
    query_count: int,
    minimum_queries: int,
) -> dict[str, bool | None]:
    return {
        "golden_query_count": query_count >= minimum_queries,
        "citation_precision_at_5": float(citation_results["citation_precision_at_k"])
        >= thresholds["citation_precision_at_5"],
        "citation_recall_at_5": float(citation_results["citation_recall_at_k"])
        >= thresholds["citation_recall_at_5"],
        "faithfulness": None,
        "answer_relevance": None,
    }


def _metric_value(results: dict[str, object], key: str) -> float:
    value = results.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Ragas result '{key}' is not numeric.")
    return float(value)


async def _score_external(
    cases: list[RAGEvaluationCase],
    judge_config: dict[str, Any],
) -> dict[str, object]:
    judge = GuardedOpenAIRagasJudge(
        model=str(judge_config["model"]),
        tenant_id="rag-evaluation",
        tenant_opted_in=True,
    )
    try:
        scorer = RagasMetricScorer(
            llm=judge.llm,
            embeddings=LocalRagasEmbedding(),
            answer_relevancy_strictness=int(judge_config["answer_relevancy_strictness"]),
        )
        return await evaluate_ragas(cases, scorer)
    finally:
        await judge.aclose()


def _source_git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
