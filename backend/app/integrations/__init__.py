"""Provider interfaces and local test doubles for external integrations."""

from backend.app.integrations.base import (
    IntegrationHealth,
    LookupQuery,
    Provider,
    Snapshot,
    SnapshotRecord,
)

__all__ = ["IntegrationHealth", "LookupQuery", "Provider", "Snapshot", "SnapshotRecord"]
