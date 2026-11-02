"""Load the local approved-issuer registry used by verifier rules."""

import csv
from pathlib import Path

from backend.app.core.logging import get_logger

_LOGGER = get_logger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATH = _PROJECT_ROOT / "data" / "registry" / "approved_issuers.csv"
_REQUIRED_COLUMNS = {"normalized_name", "canonical_name", "status", "is_mock"}


def load_approved_issuers(path: Path = _REGISTRY_PATH) -> dict[str, str]:
    """Load active issuers as normalized-name to canonical-name mappings."""
    with path.open(encoding="utf-8", newline="") as registry_file:
        reader = csv.DictReader(registry_file)
        columns = set(reader.fieldnames or [])
        if not _REQUIRED_COLUMNS.issubset(columns):
            missing = sorted(_REQUIRED_COLUMNS - columns)
            raise ValueError(f"Issuer registry is missing required columns: {missing}")

        issuers: dict[str, str] = {}
        mock_rows = 0
        for line_number, row in enumerate(reader, start=2):
            normalized_name = (row["normalized_name"] or "").strip().casefold()
            canonical_name = (row["canonical_name"] or "").strip()
            status = (row["status"] or "").strip().casefold()
            if not normalized_name or not canonical_name:
                raise ValueError(f"Issuer registry has an incomplete row at line {line_number}")
            if status != "active":
                continue
            issuers[normalized_name] = canonical_name
            if (row["is_mock"] or "").strip().casefold() == "true":
                mock_rows += 1

    if not issuers:
        raise ValueError(f"Issuer registry contains no active issuers: {path}")
    if mock_rows:
        _LOGGER.warning(
            "MOCK issuer registry loaded: %s active records are test data.",
            mock_rows,
        )
    return issuers
