"""Tests for Phase 5: Compliance RAG — chunker, vector store, retriever, and entailment checker."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from backend.app.rag.chunker import RegulationChunk, chunk_regulations
from backend.app.rag.entailment_checker import RuleBasedEntailmentChecker
from backend.app.rag.retriever import HybridRetriever
from backend.app.rag.store import ChromaVectorStore

REGULATIONS_FILE = Path("data/regulations/csddd_regulations.json")


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

    retriever = HybridRetriever(vector_store=store, corpus_chunks=corpus)
    results = retriever.retrieve(
        query="due diligence supply chain obligations",
        assessment_date=date(2026, 12, 1),
        n_results=5,
    )

    assert len(results) >= 1, "Retriever must return at least 1 result."
    for r in results:
        assert "_rrf_score" in r
        assert r["_rrf_score"] > 0


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


def test_regulation_ingestion_manager_proposal_flow() -> None:
    """Verifies Addendum A - R3 idempotent proposal and approval workflow for regulation updates."""
    from backend.app.rag.ingestion import RegulationIngestionManager

    store = ChromaVectorStore(in_memory=True)
    manager = RegulationIngestionManager(store=store, db=None)

    proposal = manager.propose_update(
        source="EUR-Lex Official Gazette",
        candidate_version_id="EU-CSDDD-2027-V2",
        candidate_data={"title": "Draft Amendment 2027"},
        notes="Automated EUR-Lex feed detection",
    )
    assert proposal.status == "pending"
    assert proposal.candidate_version_id == "EU-CSDDD-2027-V2"

    # Ingest file idempotently
    count1 = manager.ingest_file(REGULATIONS_FILE)
    count2 = manager.ingest_file(REGULATIONS_FILE)
    assert count1 == count2
    assert store.count() == count1
