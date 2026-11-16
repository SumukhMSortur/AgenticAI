"""Importer for real factory audit histories to train or update risk models."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AuditRecordInput(BaseModel):
    audit_date: str
    non_compliances_minor: int = Field(ge=0)
    non_compliances_major: int = Field(ge=0)
    non_compliances_critical: int = Field(ge=0)
    passed: bool


class FactoryAuditHistoryInput(BaseModel):
    factory_id: str
    history: list[AuditRecordInput]


class AuditHistoryImporter:
    """Validates and ingests audit history datasets in CSV or JSON format."""

    @classmethod
    def import_csv(cls, csv_content: str) -> dict[str, list[dict[str, Any]]]:
        """Parse CSV with columns: factory_id, audit_date, minor, major, critical, passed."""
        reader = csv.DictReader(io.StringIO(csv_content))
        factories: dict[str, list[dict[str, Any]]] = {}
        for row in reader:
            fid = row["factory_id"].strip()
            factories.setdefault(fid, []).append({
                "audit_date": row["audit_date"].strip(),
                "non_compliances_minor": int(row.get("minor", 0)),
                "non_compliances_major": int(row.get("major", 0)),
                "non_compliances_critical": int(row.get("critical", 0)),
                "passed": row.get("passed", "true").lower() in ("true", "1", "yes"),
            })
        return factories

    @classmethod
    def import_json(cls, json_content: str) -> dict[str, list[dict[str, Any]]]:
        data = json.loads(json_content)
        factories = data.get("factories", [])
        return {
            str(f["factory_id"]): f["history"]
            for f in factories
            if "factory_id" in f and "history" in f
        }
