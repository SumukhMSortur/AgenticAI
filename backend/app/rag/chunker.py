"""Legal regulation chunker: splits versioned regulation JSON into article/recital/annex chunks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class RegulationChunk:
    """A single chunk of legal text with provenance metadata."""

    chunk_id: str
    text: str
    regulation_id: str
    version_id: str
    parent_id: str
    jurisdiction: str
    effective_from: date
    superseded_by: str | None  # ISO date string or None
    section_type: str  # "recital" | "article" | "annex" | "preamble"
    section_number: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _parse_date(value: str) -> date:
    """Parse an ISO 8601 date string to a date object."""
    return date.fromisoformat(value[:10])


def chunk_regulations(regulations_path: Path) -> list[RegulationChunk]:
    """Load and chunk versioned regulation JSON into legal-structure chunks.

    Each article, recital, and annex becomes a separate chunk with full provenance.
    """
    with open(regulations_path, encoding="utf-8") as f:
        regs: list[dict[str, Any]] = json.load(f)

    # Build a lookup for successor effective dates if superseded_by points to a version_id
    version_effective_map: dict[str, str] = {
        r.get("version_id", ""): r.get("effective_from", "")
        for r in regs
        if r.get("version_id") and r.get("effective_from")
    }

    chunks: list[RegulationChunk] = []

    for reg in regs:
        reg_id: str = reg["regulation_id"]
        version_id: str = reg.get("version_id", reg_id)
        jurisdiction: str = reg.get("jurisdiction", "EU")
        effective_from: date = _parse_date(reg["effective_from"])
        raw_superseded_by: str | None = reg.get("superseded_by")
        # Resolve superseded date: if it points to another version_id, use that version's effective_from
        superseded_date: str | None = None
        if raw_superseded_by:
            superseded_date = version_effective_map.get(raw_superseded_by, raw_superseded_by)

        title: str = reg.get("title", "")

        # ---- Preamble ----
        preamble: str = reg.get("preamble", "").strip()
        if preamble:
            chunks.append(
                RegulationChunk(
                    chunk_id=f"{version_id}::preamble",
                    text=f"[Preamble] {title}\n\n{preamble}",
                    regulation_id=reg_id,
                    version_id=version_id,
                    parent_id=version_id,
                    jurisdiction=jurisdiction,
                    effective_from=effective_from,
                    superseded_by=superseded_date,
                    section_type="preamble",
                    section_number="0",
                    metadata={"title": title},
                )
            )

        # ---- Sections (Articles / Recitals / Annexes) ----
        for section in reg.get("sections", []):
            sec_id: str = str(section.get("section_id", ""))
            kind: str = section.get("kind", "article")
            art_num: str = section.get("article", sec_id)
            sec_title: str = section.get("title", "")
            sec_text: str = section.get("text", "").strip()
            keywords: list[str] = section.get("keywords", [])

            if not sec_text:
                continue

            chunks.append(
                RegulationChunk(
                    chunk_id=f"{version_id}::{sec_id}",
                    text=f"[{art_num}{(' – ' + sec_title) if sec_title else ''}]\n\n{sec_text}",
                    regulation_id=reg_id,
                    version_id=version_id,
                    parent_id=str(section.get("parent_section_id") or version_id),
                    jurisdiction=jurisdiction,
                    effective_from=effective_from,
                    superseded_by=superseded_date,
                    section_type=kind,
                    section_number=art_num,
                    metadata={
                        "title": title,
                        "section_title": sec_title,
                        "keywords": ", ".join(keywords),
                    },
                )
            )

    return chunks
