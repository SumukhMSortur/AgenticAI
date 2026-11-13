"""Deterministic provider fakes for unit and golden-set tests."""

from datetime import UTC, datetime

from backend.app.integrations.base import (
    IntegrationHealth,
    LookupQuery,
    Provider,
    Snapshot,
    SnapshotRecord,
)


class FakeProvider(Provider):
    """In-memory provider with explicit refresh and deterministic local lookup."""

    def __init__(
        self,
        source: str = "fake",
        records: list[SnapshotRecord] | None = None,
        unavailable: bool = False,
    ) -> None:
        self.source = source
        self._records = list(records or [])
        self._unavailable = unavailable
        self._snapshot: Snapshot | None = None

    def refresh(self) -> Snapshot:
        """Create a stable snapshot from records supplied by the test."""
        if self._unavailable:
            raise RuntimeError(f"Provider '{self.source}' is unavailable")
        self._snapshot = Snapshot(
            source=self.source,
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            snapshot_hash=f"fake:{self.source}:snapshot-v1",
            records=self._records,
        )
        return self._snapshot

    def lookup(self, query: LookupQuery) -> list[SnapshotRecord]:
        """Perform a stable, case-insensitive lookup against the loaded snapshot."""
        if self._snapshot is None:
            raise RuntimeError("Provider snapshot must be refreshed before lookup")
        if self._unavailable:
            raise RuntimeError(f"Provider '{self.source}' is unavailable")
        name = (query.name or "").strip().casefold()
        country = (query.country or "").strip().casefold()
        matches: list[SnapshotRecord] = []
        for record in self._snapshot.records:
            if name and record.normalized_name.strip().casefold() != name:
                continue
            if country and (record.country or "").strip().casefold() != country:
                continue
            if any(record.identifiers.get(key) != value for key, value in query.identifiers.items()):
                continue
            matches.append(record)
        return sorted(matches, key=lambda record: record.record_key)

    def health(self) -> IntegrationHealth:
        """Report the fake's configured availability."""
        if self._unavailable:
            return IntegrationHealth(
                available=False,
                status="unavailable",
                message=f"Provider '{self.source}' is unavailable",
            )
        return IntegrationHealth(available=True, status="healthy")
