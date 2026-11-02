"""Generates the approved certificate issuer registry (mock registry)."""

import csv
from pathlib import Path

REGISTRY_DIR = Path("data/registry")
REGISTRY_FILE = REGISTRY_DIR / "approved_issuers.csv"

MOCK_ISSUERS = [
    {
        "issuer_id": "ISS-001",
        "canonical_name": "Control Union Certifications B.V.",
        "normalized_name": "control union certifications b.v.",
        "short_name": "Control Union",
        "accreditation_body": "IOAS / ISO 17065",
        "standards": "GOTS;GRS;RCS;OCS;FSC",
        "valid_from": "2015-01-01",
        "valid_to": "2030-12-31",
        "status": "active",
        "is_mock": "TRUE",
    },
    {
        "issuer_id": "ISS-002",
        "canonical_name": "Ecocert Greenlife S.A.S.",
        "normalized_name": "ecocert greenlife s.a.s.",
        "short_name": "Ecocert",
        "accreditation_body": "COFRAC / ISO 17065",
        "standards": "GOTS;OCS;COSMOS",
        "valid_from": "2016-01-01",
        "valid_to": "2029-12-31",
        "status": "active",
        "is_mock": "TRUE",
    },
    {
        "issuer_id": "ISS-003",
        "canonical_name": "OEKO-TEX Association (Service GmbH)",
        "normalized_name": "oeko-tex association service gmbh",
        "short_name": "OEKO-TEX",
        "accreditation_body": "OEKO-TEX International",
        "standards": "STANDARD 100;MADE IN GREEN;LEATHER STANDARD;ECO PASSPORT",
        "valid_from": "2010-01-01",
        "valid_to": "2032-12-31",
        "status": "active",
        "is_mock": "TRUE",
    },
    {
        "issuer_id": "ISS-004",
        "canonical_name": "SGS Société Générale de Surveillance SA",
        "normalized_name": "sgs societe generale de surveillance sa",
        "short_name": "SGS",
        "accreditation_body": "SAS / ISO 17025 / ISO 17065",
        "standards": "ISO 14001;ISO 9001;ZDHC;HIGG",
        "valid_from": "2012-01-01",
        "valid_to": "2031-12-31",
        "status": "active",
        "is_mock": "TRUE",
    },
    {
        "issuer_id": "ISS-005",
        "canonical_name": "Intertek Group plc",
        "normalized_name": "intertek group plc",
        "short_name": "Intertek",
        "accreditation_body": "UKAS / ISO 17025",
        "standards": "GOTS;ToxClear;ZDHC MRSL;WRAP",
        "valid_from": "2014-01-01",
        "valid_to": "2030-06-30",
        "status": "active",
        "is_mock": "TRUE",
    },
    {
        "issuer_id": "ISS-006",
        "canonical_name": "Bureau Veritas SA",
        "normalized_name": "bureau veritas sa",
        "short_name": "Bureau Veritas",
        "accreditation_body": "COFRAC / ISO 17065",
        "standards": "GOTS;GRS;ISO 14001;SA8000",
        "valid_from": "2015-05-01",
        "valid_to": "2028-12-31",
        "status": "active",
        "is_mock": "TRUE",
    },
    {
        "issuer_id": "ISS-007",
        "canonical_name": "TÜV Rheinland LGA Products GmbH",
        "normalized_name": "tuv rheinland lga products gmbh",
        "short_name": "TÜV Rheinland",
        "accreditation_body": "DAkkS / ISO 17065",
        "standards": "OEKO-TEX;ZDHC;ISO 14001",
        "valid_from": "2018-01-01",
        "valid_to": "2029-06-30",
        "status": "active",
        "is_mock": "TRUE",
    },
]


def generate_issuer_registry() -> Path:
    """Writes the approved mock issuer registry CSV."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = list(MOCK_ISSUERS[0].keys())

    with open(REGISTRY_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for issuer in MOCK_ISSUERS:
            writer.writerow(issuer)

    print(f"Generated {len(MOCK_ISSUERS)} mock issuers at {REGISTRY_FILE}")
    return REGISTRY_FILE


if __name__ == "__main__":
    generate_issuer_registry()
