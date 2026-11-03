"""Idempotent and version-aware regulation ingestion with human-in-the-loop proposals (Addendum A - R3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.db.audit_log import append_audit_event
from backend.app.db.models import RegulationUpdateProposal
from backend.app.rag.chunker import chunk_regulations
from backend.app.rag.store import ChromaVectorStore

logger = get_logger(__name__)

DEFAULT_REGULATIONS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "regulations" / "csddd_regulations.json"
)


class RegulationIngestionManager:
    """Manages versioned, idempotent regulation ingestion into RAG and tracks candidate proposals."""

    def __init__(
        self,
        store: ChromaVectorStore,
        db: Session | None = None,
        regulations_path: Path = DEFAULT_REGULATIONS_PATH,
    ) -> None:
        self.store = store
        self.db = db
        self.regulations_path = regulations_path

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
        regulations_path: Path | None = None,
        tenant_id: str = "system",
        notes: str | None = None,
    ) -> int:
        """Record a human decision before idempotently ingesting the approved version."""
        if self.db is None:
            raise RuntimeError("A database session is required to approve a regulation update.")

        proposal = self.db.query(RegulationUpdateProposal).filter_by(id=proposal_id).first()
        if proposal is None:
            raise ValueError(f"Proposal '{proposal_id}' not found.")
        if proposal.status == "rejected":
            raise ValueError(f"Rejected proposal '{proposal_id}' cannot be ingested.")

        source_id = self._source_id_for_version(
            regulations_path or self.regulations_path,
            proposal.candidate_version_id,
        )
        if proposal.status == "pending":
            proposal.status = "approved"
            proposal.reviewer_id = reviewer_id
            proposal.decided_at = datetime.now(UTC)
            proposal.notes = notes

            append_audit_event(
                db=self.db,
                tenant_id=tenant_id,
                event_type="regulation_update_decided",
                doc_hash=proposal.candidate_version_id,
                reviewer_decision={"status": "approved", "reviewer_id": reviewer_id},
                payload={"proposal_id": proposal_id, "notes": notes},
            )

        count = self._ingest_version(
            source_id,
            proposal.candidate_version_id,
            regulations_path or self.regulations_path,
        )
        logger.info(f"Proposal '{proposal_id}' approved by reviewer '{reviewer_id}'. Ingested {count} chunks.")
        return count

    def ingest(
        self,
        source_id: str,
        version_id: str,
        regulations_path: Path | None = None,
    ) -> int:
        """Idempotently ingest a version only after a persisted human approval."""
        if self.db is None:
            raise RuntimeError("A database session is required for approved version ingestion.")
        proposal = (
            self.db.query(RegulationUpdateProposal)
            .filter_by(candidate_version_id=version_id, status="approved")
            .first()
        )
        if proposal is None:
            raise ValueError(f"Version '{version_id}' has no approved update proposal.")
        return self._ingest_version(
            source_id,
            version_id,
            regulations_path or self.regulations_path,
        )

    def _ingest_version(
        self,
        source_id: str,
        version_id: str,
        regulations_path: Path,
    ) -> int:
        chunks = chunk_regulations(regulations_path)
        selected = [
            chunk
            for chunk in chunks
            if chunk.regulation_id == source_id and chunk.version_id == version_id
        ]
        if not selected:
            raise ValueError(
                f"No regulation chunks found for source '{source_id}' and version '{version_id}'."
            )
        self.store.upsert_chunks(selected)
        return len(selected)

    def ingest_file(self, regulations_path: Path) -> int:
        """Bootstrap an empty vector store from the checked-in regulation corpus."""
        if self.store.count() != 0:
            raise RuntimeError(
                "Bulk regulation bootstrap is allowed only for an empty store; "
                "use an approved version update."
            )
        chunks = chunk_regulations(regulations_path)
        self.store.upsert_chunks(chunks)
        return len(chunks)

    @staticmethod
    def _source_id_for_version(regulations_path: Path, version_id: str) -> str:
        sources = {
            chunk.regulation_id
            for chunk in chunk_regulations(regulations_path)
            if chunk.version_id == version_id
        }
        if len(sources) != 1:
            raise ValueError(
                f"Expected exactly one regulation source for version '{version_id}', found {len(sources)}."
            )
        return next(iter(sources))
