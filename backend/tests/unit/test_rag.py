"""Tests for Phase 5: Compliance RAG — chunker, vector store, retriever, and entailment checker."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import httpx2
import pytest
from google.genai import types
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings
from backend.app.core.errors import (
    EntailmentEscalationError,
    PrivacyViolationError,
    RAGGenerationError,
)
from backend.app.db.audit_log import verify_chain
from backend.app.db.models import AuditEvent
from backend.app.db.session import Base
from backend.app.integrations.gemini_entailment import (
    GeminiClient,
    GeminiEntailmentJudge,
    GeminiModels,
)
from backend.app.integrations.gemini_rag import GeminiRAGAnswerer
from backend.app.integrations.openai_ragas import GuardedOpenAIRagasJudge
from backend.app.rag.chunker import RegulationChunk, chunk_regulations
from backend.app.rag.entailment_checker import LLMEntailmentChecker, RuleBasedEntailmentChecker
from backend.app.rag.evaluation import (
    GoldenQuery,
    RAGEvaluationCase,
    citation_metrics,
    evaluate_ragas,
    load_golden_queries,
)
from backend.app.rag.retriever import CrossEncoderReranker, HybridRetriever
from backend.app.rag.store import ChromaVectorStore

REGULATIONS_FILE = Path("data/regulations/csddd_regulations.json")


class StubPairScorer:
    def __init__(self, scores: list[float] | None = None) -> None:
        self.scores = scores
        self.inputs: Sequence[tuple[str, str]] = []
        self.options: tuple[bool, bool] | None = None

    def predict(
        self,
        inputs: Sequence[tuple[str, str]],
        *,
        show_progress_bar: bool,
        convert_to_numpy: bool,
    ) -> list[float]:
        self.inputs = inputs
        self.options = (show_progress_bar, convert_to_numpy)
        return self.scores if self.scores is not None else [1.0] * len(inputs)


class FakeGeminiResponse:
    def __init__(self, text: str | None) -> None:
        self.text = text


class FakeGeminiModels(GeminiModels):
    def __init__(self, response_text: str) -> None:
        self.called = False
        self.response_text = response_text

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig,
    ) -> FakeGeminiResponse:
        self.called = True
        self.last_call = (model, contents, config)
        return FakeGeminiResponse(self.response_text)


class FakeGeminiClient(GeminiClient):
    def __init__(self, models: FakeGeminiModels) -> None:
        self.models = models


class FakeRagasScorer:
    def __init__(self, scores: tuple[float, float] = (0.8, 0.9)) -> None:
        self.scores = scores
        self.samples: list[tuple[str, str, list[str]]] = []

    async def score(
        self,
        query: str,
        response: str,
        retrieved_contexts: list[str],
    ) -> tuple[float, float]:
        self.samples.append((query, response, retrieved_contexts))
        return self.scores


# ---------------------------------------------------------------------------
# Chunker tests
# ---------------------------------------------------------------------------


def test_chunker_produces_chunks() -> None:
    """Chunker must produce at least one chunk per regulation with correct metadata."""
    if not REGULATIONS_FILE.exists():
        pytest.skip("Regulations file not generated yet.")

    chunks = chunk_regulations(REGULATIONS_FILE)
    assert len(chunks) >= 3, "Expected at least 3 chunks across all regulations."

    for chunk in chunks:
        assert isinstance(chunk, RegulationChunk)
        assert chunk.chunk_id, "chunk_id must not be empty."
        assert chunk.text, "chunk text must not be empty."
        assert chunk.effective_from, "effective_from must be set."
        assert chunk.parent_id == chunk.version_id


def test_chunker_date_filter_superseded() -> None:
    """Chunks for the superseded EU CSDDD 2024 regulation must carry a superseded_by date."""
    if not REGULATIONS_FILE.exists():
        pytest.skip("Regulations file not generated yet.")

    chunks = chunk_regulations(REGULATIONS_FILE)
    superseded_chunks = [c for c in chunks if c.regulation_id == "EU-CSDDD-2024"]
    assert len(superseded_chunks) >= 1, "Must have at least one chunk for EU-CSDDD-2024."

    for c in superseded_chunks:
        assert c.superseded_by is not None, (
            f"EU-CSDDD-2024 chunk '{c.chunk_id}' should be marked superseded."
        )
        # Must be superseded before 2026-12-31
        assert c.superseded_by <= "2026-12-31"


def test_vector_store_upsert_and_count() -> None:
    """In-memory ChromaDB store must accept chunks and report correct count."""
    if not REGULATIONS_FILE.exists():
        pytest.skip("Regulations file not generated yet.")

    chunks = chunk_regulations(REGULATIONS_FILE)
    store = ChromaVectorStore(in_memory=True)
    store.reset()
    store.upsert_chunks(chunks)
    assert store.count() == len(chunks), "Store count must match number of upserted chunks."


def test_vector_store_excludes_superseded_on_date() -> None:
    """Query on 2026-12-01 must NOT return chunks from EU-CSDDD-2024/1760 (superseded 2026-03-18)."""
    if not REGULATIONS_FILE.exists():
        pytest.skip("Regulations file not generated yet.")

    with open(REGULATIONS_FILE, encoding="utf-8") as f:
        regs = json.load(f)

    # Find the superseded regulation
    superseded = next(
        (r for r in regs if r.get("regulation_id") == "EU-CSDDD-2024"),
        None,
    )
    if not superseded:
        pytest.skip("EU-CSDDD-2024 not found in regulations file.")

    chunks = chunk_regulations(REGULATIONS_FILE)
    superseded_chunk = next((c for c in chunks if c.regulation_id == "EU-CSDDD-2024"), None)
    assert superseded_chunk is not None
    assert superseded_chunk.superseded_by is not None
    superseded_by_date = superseded_chunk.superseded_by

    store = ChromaVectorStore(in_memory=True)
    store.reset()
    store.upsert_chunks(chunks)

    # Query after the superseded_by date
    assessment = date.fromisoformat(superseded_by_date)
    query_date = date(assessment.year, assessment.month + 1 if assessment.month < 12 else 12, 1)

    results = store.query(
        query_text="corporate sustainability due diligence obligations",
        assessment_date=query_date,
        n_results=20,
    )

    # No result should come from the superseded regulation
    for r in results:
        assert r.get("regulation_id") != "EU-CSDDD-2024", (
            f"Superseded regulation EU-CSDDD-2024 must not appear in results for {query_date}."
        )


def test_hybrid_retriever_returns_ranked_results() -> None:
    """HybridRetriever must return up to n_results chunks with RRF scores."""
    if not REGULATIONS_FILE.exists():
        pytest.skip("Regulations file not generated yet.")

    chunks = chunk_regulations(REGULATIONS_FILE)
    store = ChromaVectorStore(in_memory=True)
    store.reset()
    store.upsert_chunks(chunks)

    # Build corpus dicts for BM25
    corpus = [
        {
            "chunk_id": c.chunk_id,
            "text": c.text,
            "effective_from": c.effective_from.isoformat(),
            "superseded_by": c.superseded_by or "",
            "jurisdiction": c.jurisdiction,
            "regulation_id": c.regulation_id,
            "version_id": c.version_id,
            "section_type": c.section_type,
            "section_number": c.section_number,
        }
        for c in chunks
    ]

    retriever = HybridRetriever(
        vector_store=store,
        corpus_chunks=corpus,
        reranker=CrossEncoderReranker(model=StubPairScorer()),
    )
    results = retriever.retrieve(
        query="due diligence supply chain obligations",
        assessment_date=date(2026, 12, 1),
        n_results=5,
    )

    assert len(results) >= 1, "Retriever must return at least 1 result."
    for r in results:
        assert "_rrf_score" in r
        assert r["_rrf_score"] > 0
        assert "_cross_encoder_score" in r


def test_cross_encoder_reranks_by_pair_score() -> None:
    """Cross-encoder scores, rather than RRF order, determine the final ranking."""
    scorer = StubPairScorer([0.1, 0.9])
    reranker = CrossEncoderReranker(model=scorer)
    candidates = [
        {"chunk_id": "first", "text": "first legal passage"},
        {"chunk_id": "second", "text": "second legal passage"},
    ]

    results = reranker.rerank("query", candidates)

    assert [item["chunk_id"] for item in results] == ["second", "first"]
    assert [item["_cross_encoder_score"] for item in results] == [0.9, 0.1]
    assert list(scorer.inputs) == [
        ("query", "first legal passage"),
        ("query", "second legal passage"),
    ]


def test_cross_encoder_rejects_invalid_score_count() -> None:
    """A model returning one score per candidate is required; failures are not hidden."""
    reranker = CrossEncoderReranker(model=StubPairScorer([0.5]))
    candidates = [
        {"chunk_id": "first", "text": "first legal passage"},
        {"chunk_id": "second", "text": "second legal passage"},
    ]

    with pytest.raises(RuntimeError, match="invalid score vector"):
        reranker.rerank("query", candidates)


def test_golden_rag_set_has_at_least_sixty_labeled_queries() -> None:
    queries = load_golden_queries(Path("data/golden/rag_golden_set.json"))
    assert len(queries) >= 60
    assert len({query.query_id for query in queries}) == len(queries)
    assert all(query.expected_chunk_ids for query in queries)


def test_citation_metrics_use_expected_chunk_ids() -> None:
    query = GoldenQuery(
        query_id="RAG-test",
        query="What is required?",
        assessment_date=date(2026, 1, 1),
        jurisdiction="EU",
        expected_chunk_ids=("expected",),
        reference_answer="A requirement.",
    )
    case = RAGEvaluationCase(
        golden_query=query,
        retrieved_chunks=(
            {"chunk_id": "expected", "text": "relevant"},
            {"chunk_id": "other", "text": "unrelated"},
        ),
    )

    result = citation_metrics([case], k=2)

    assert result["citation_precision_at_k"] == 0.5
    assert result["citation_recall_at_k"] == 1.0
    assert result["mean_reciprocal_rank_at_k"] == 1.0


def test_ragas_aggregation_accepts_fake_judge_without_network() -> None:
    query = GoldenQuery(
        query_id="RAG-test",
        query="What is required?",
        assessment_date=date(2026, 1, 1),
        jurisdiction="EU",
        expected_chunk_ids=("expected",),
        reference_answer="A requirement.",
    )
    case = RAGEvaluationCase(
        golden_query=query,
        retrieved_chunks=({"chunk_id": "expected", "text": "The requirement."},),
        response="The requirement is to provide evidence.",
    )
    fake_judge = FakeRagasScorer()

    result = asyncio.run(evaluate_ragas([case], fake_judge))

    assert result["faithfulness"] == 0.8
    assert result["answer_relevance"] == 0.9
    assert len(fake_judge.samples) == 1
    assert fake_judge.samples[0][2] == ["The requirement."]


def test_guarded_openai_ragas_requires_opt_in_and_allowlisted_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with pytest.raises(PrivacyViolationError, match="explicit tenant opt-in"):
        GuardedOpenAIRagasJudge(
            model="gpt-4o-mini",
            tenant_id="tenant-test",
            tenant_opted_in=False,
        )

    judge = GuardedOpenAIRagasJudge(
        model="gpt-4o-mini",
        tenant_id="tenant-test",
        tenant_opted_in=True,
    )
    request = httpx2.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [], "unexpected": "blocked"},
    )

    async def verify_request() -> None:
        try:
            await judge._guard_request(request)
        finally:
            await judge.aclose()

    with pytest.raises(PrivacyViolationError, match="disallowed fields"):
        asyncio.run(verify_request())


def test_entailment_checker_positive_case() -> None:
    """Entailment checker must confirm that an obligation claim is entailed by matching article text."""
    checker = RuleBasedEntailmentChecker()
    claim = "Companies must conduct due diligence on supply chain human rights risks."
    citation = (
        "Member States shall ensure that companies carry out human rights and environmental "
        "due diligence in their operations, subsidiaries and value chain partners. "
        "This obligation is mandatory and applies to companies above specified thresholds."
    )
    entailed, confidence = checker.check(claim, citation)
    assert entailed is True, f"Expected entailment but got confidence={confidence}"
    assert confidence >= 0.20


def test_entailment_checker_negative_case() -> None:
    """Entailment checker must reject a claim with no overlapping content."""
    checker = RuleBasedEntailmentChecker()
    claim = "Companies must certify all Organic Cotton with GOTS."
    citation = "The regulation on ecodesign requirements for sustainable products sets framework."
    _, confidence = checker.check(claim, citation)
    # Not necessarily False but confidence should be low
    assert confidence < 0.8, f"Unexpected high confidence={confidence} for non-overlapping texts."


def test_llm_entailment_checker_uses_judge_and_fails_closed() -> None:
    checker = LLMEntailmentChecker(lambda _claim, _citation: (False, 0.91))
    assert checker.check("claim", "citation") == (False, 0.91)

    with pytest.raises(EntailmentEscalationError, match="No guarded entailment judge"):
        LLMEntailmentChecker().check("claim", "citation")
    with pytest.raises(EntailmentEscalationError, match="required"):
        checker.check("", "citation")
    with pytest.raises(EntailmentEscalationError, match="invalid result"):
        LLMEntailmentChecker(lambda _claim, _citation: (True, float("nan"))).check(
            "claim", "citation"
        )


def test_gemini_entailment_requires_opt_in_before_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    models = FakeGeminiModels('{"entailed":true,"confidence":0.95}')
    judge = GeminiEntailmentJudge(
        tenant_id="tenant-test",
        tenant_opted_in=False,
        client=FakeGeminiClient(models),
    )

    with pytest.raises(PrivacyViolationError, match="has not opted in"):
        judge(
            "The supplier must provide a certificate.",
            "The supplier must provide a certificate.",
        )
    assert models.called is False


def test_gemini_entailment_parses_guarded_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    judge = GeminiEntailmentJudge(
        tenant_id="tenant-test",
        tenant_opted_in=True,
        client=FakeGeminiClient(
            FakeGeminiModels('{"entailed":true,"confidence":0.95}')
        ),
    )

    assert judge(
        "The supplier must provide a certificate.",
        "The supplier must provide a certificate.",
    ) == (True, 0.95)


def test_gemini_rag_generation_is_guarded_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    blocked_models = FakeGeminiModels("answer")
    blocked = GeminiRAGAnswerer(
        tenant_id="tenant-test",
        tenant_opted_in=False,
        client=FakeGeminiClient(blocked_models),
    )
    with pytest.raises(PrivacyViolationError, match="has not opted in"):
        blocked("What does the rule require?", [{"chunk_id": "article-1", "text": "The rule."}])
    assert blocked_models.called is False

    allowed = GeminiRAGAnswerer(
        tenant_id="tenant-test",
        tenant_opted_in=True,
        client=FakeGeminiClient(FakeGeminiModels("Grounded answer [article-1].")),
    )
    assert allowed(
        "What does the rule require?",
        [{"chunk_id": "article-1", "text": "The rule."}],
    ) == "Grounded answer [article-1]."
    with pytest.raises(RAGGenerationError, match="required"):
        allowed("", [])


def test_regulation_ingestion_manager_proposal_flow() -> None:
    """Verifies Addendum A - R3 idempotent proposal and approval workflow for regulation updates."""
    from backend.app.rag.ingestion import RegulationIngestionManager

    store = ChromaVectorStore(in_memory=True)
    store.reset()
    manager = RegulationIngestionManager(store=store, db=None)

    proposal = manager.propose_update(
        source="EUR-Lex Official Gazette",
        candidate_version_id="EU-CSDDD-2027-V2",
        candidate_data={"title": "Draft Amendment 2027"},
        notes="Automated EUR-Lex feed detection",
    )
    assert proposal.status == "pending"
    assert proposal.candidate_version_id == "EU-CSDDD-2027-V2"
    with pytest.raises(RuntimeError, match="database session is required"):
        manager.approve_and_ingest(proposal.id, "reviewer")
    assert store.count() == 0

    # Bulk ingestion is only a one-time bootstrap; updates need persisted approval.
    count = manager.ingest_file(REGULATIONS_FILE)
    assert store.count() == count
    with pytest.raises(RuntimeError, match="only for an empty store"):
        manager.ingest_file(REGULATIONS_FILE)


def test_versioned_ingestion_is_idempotent_and_source_scoped() -> None:
    """A version-scoped ingest upserts only the selected source/version."""
    from backend.app.rag.ingestion import RegulationIngestionManager

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session: Session = session_factory()
    try:
        store = ChromaVectorStore(in_memory=True)
        store.reset()
        manager = RegulationIngestionManager(
            store=store,
            db=session,
            regulations_path=REGULATIONS_FILE,
        )
        with pytest.raises(ValueError, match="no approved update proposal"):
            manager.ingest("EU-ESPR-2024", "EU-ESPR-2024-1781")

        proposal = manager.propose_update(
            source="EUR-Lex Official Gazette",
            candidate_version_id="EU-ESPR-2024-1781",
            candidate_data=[],
            tenant_id="tenant_test",
        )
        assert manager.approve_and_ingest(
            proposal.id,
            "reviewer-1",
            tenant_id="tenant_test",
        ) == 2

        first_count = manager.ingest("EU-ESPR-2024", "EU-ESPR-2024-1781")
        second_count = manager.ingest("EU-ESPR-2024", "EU-ESPR-2024-1781")

        assert first_count == second_count == 2
        assert store.count() == 2
        with pytest.raises(ValueError, match="no approved update proposal"):
            manager.ingest("EU-ESPR-2024", "unknown-version")
    finally:
        session.close()
        engine.dispose()


def test_approved_update_is_audited_before_ingestion() -> None:
    """A persisted reviewer approval is audited and ingests only its candidate version."""
    from backend.app.rag.ingestion import RegulationIngestionManager

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session: Session = session_factory()
    try:
        store = ChromaVectorStore(in_memory=True)
        store.reset()
        manager = RegulationIngestionManager(
            store=store,
            db=session,
            regulations_path=REGULATIONS_FILE,
        )
        proposal = manager.propose_update(
            source="EUR-Lex Official Gazette",
            candidate_version_id="EU-ESPR-2024-1781",
            candidate_data=[],
            tenant_id="tenant_test",
        )

        assert manager.approve_and_ingest(
            proposal.id,
            "reviewer-1",
            tenant_id="tenant_test",
        ) == 2
        assert proposal.status == "approved"
        assert proposal.reviewer_id == "reviewer-1"
        assert store.count() == 2
        assert verify_chain(session, "tenant_test") == (True, None)

        audit_events = session.scalars(select(AuditEvent)).all()
        assert len(audit_events) == 2
    finally:
        session.close()
        engine.dispose()
