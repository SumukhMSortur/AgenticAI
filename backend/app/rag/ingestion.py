"""Idempotent and version-aware regulation ingestion with human-in-the-loop proposals (Addendum A - R3)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.db.audit_log import append_audit_event
from backend.app.db.models import RegulationUpdateProposal
from backend.app.rag.chunker import chunk_regulations
from backend.app.rag.store import ChromaVectorStore

logger = get_logger(__name__)


class RegulationIngestionManager:
    """Manages versioned, idempotent regulation ingestion into RAG and tracks candidate proposals."""

    def __init__(self, store: ChromaVectorStore, db: Session | None = None) -> None:
        self.store = store
        self.db = db

    def propose_update(
        self,
        source: str,
        candidate_version_id: str,
        candidate_data: list[dict[str, Any]] | dict[str, Any],
        notes: str | None = None,
        tenant_id: str = "system",
    ) -> RegulationUpdateProposal:
        """Records a detected regulation update into regulation_update_proposals pending review.

        The active vector index is NEVER updated autonomously without human reviewer approval.
        """
        proposal_id = str(uuid.uuid4())
        proposal = RegulationUpdateProposal(
            id=proposal_id,
            source=source,
            candidate_version_id=candidate_version_id,
            status="pending",
            notes=f"{notes or ''} (Items: {len(candidate_data)})" if candidate_data else notes,
        )

        if self.db is not None:
            self.db.add(proposal)
            self.db.commit()

            append_audit_event(
                db=self.db,
                tenant_id=tenant_id,
                event_type="regulation_update_proposed",
                doc_hash=candidate_version_id,
                payload={
                    "proposal_id": proposal_id,
                    "source": source,
                    "candidate_version_id": candidate_version_id,
                },
            )

        logger.info(
            f"Regulation update proposal '{candidate_version_id}' created from source '{source}' (pending review)."
        )
        return proposal

    def approve_and_ingest(
        self,
        proposal_id: str,
        reviewer_id: str,
        regulations_path: Path,
        tenant_id: str = "system",
        notes: str | None = None,
    ) -> int:
        """Human approval action: records decision to audit log and idempotently ingests into vector store."""
        if self.db is not None:
            proposal = self.db.query(RegulationUpdateProposal).filter_by(id=proposal_id).first()
            if proposal is None:
                raise ValueError(f"Proposal '{proposal_id}' not found.")
            proposal.status = "approved"
            proposal.reviewer_id = reviewer_id
            proposal.notes = notes
            self.db.commit()

            append_audit_event(
                db=self.db,
                tenant_id=tenant_id,
                event_type="regulation_update_decided",
                doc_hash=proposal.candidate_version_id,
                reviewer_decision={"status": "approved", "reviewer_id": reviewer_id},
                payload={"proposal_id": proposal_id, "notes": notes},
            )

        count = self.ingest_file(regulations_path)
        logger.info(f"Proposal '{proposal_id}' approved by reviewer '{reviewer_id}'. Ingested {count} chunks.")
        return count

    def ingest_file(self, regulations_path: Path) -> int:
        """Idempotently chunks and upserts regulations into ChromaDB."""
        chunks = chunk_regulations(regulations_path)
        self.store.upsert_chunks(chunks)
        return len(chunks)
