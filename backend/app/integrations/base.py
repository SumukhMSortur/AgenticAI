"""Provider contract for explicit refresh and local snapshot lookup."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SnapshotRecord(BaseModel):
    """A normalized record persisted as part of a provider snapshot."""

    record_key: str
    normalized_name: str
    country: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Snapshot(BaseModel):
    """Immutable provider snapshot metadata and normalized records."""

    source: str
    fetched_at: datetime
    snapshot_hash: str
    records: list[SnapshotRecord] = Field(default_factory=list)


class LookupQuery(BaseModel):
    """Allowlisted query shape; contains no implicit vault data."""

    name: str | None = None
    country: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)


class IntegrationHealth(BaseModel):
    """Provider health without exposing credentials or sensitive payloads."""

    available: bool
    status: str
    message: str = ""


class Provider(ABC):
    """Synchronous provider interface; refresh is explicit and lookup is local."""

    @abstractmethod
    def refresh(self) -> Snapshot:
        """Fetch, validate, and return a new provider snapshot."""

    @abstractmethod
    def lookup(self, query: LookupQuery) -> list[SnapshotRecord]:
        """Search the current local snapshot without making a network request."""

    @abstractmethod
    def health(self) -> IntegrationHealth:
        """Report provider readiness without returning secrets."""
