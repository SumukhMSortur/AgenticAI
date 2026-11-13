"""Generates 150 labeled end-to-end compliance test cases for regression gates."""

import json
from pathlib import Path

import numpy as np

GOLDEN_DIR = Path("data/golden")
GOLDEN_FILE = GOLDEN_DIR / "golden_set.json"


def generate_golden_set(num_cases: int = 150, seed: int = 42) -> Path:
    """Generates 150 comprehensive golden benchmark test cases."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    _rng = np.random.default_rng(seed)

    cases: list[dict] = []

    # Distribution of scenarios across 150 cases:
    # ~50 fully compliant clean cases
    # ~25 expired certificate cases (V-EXP-001)
    # ~15 near expiry warning cases (V-EXP-002)
    # ~15 unapproved issuer cases (V-ISS-001)
    # ~10 fuzzy issuer typos (V-ISS-002)
    # ~15 material scope mismatch cases (V-SCOPE-001)
    # ~10 cross-document supplier mismatch (V-XDOC-001)
    # ~10 missing page / gap cases (V-PAGE-001)

    scenario_types = [
        (
            "clean_pass",
            "Fully compliant GOTS organic cotton certificate and matching BOM",
            "pass",
            "V-EXP-001",
            False,
        ),
        ("expired_cert", "Certificate expired before assessment date", "fail", "V-EXP-001", False),
        (
            "near_expiry",
            "Certificate expiring within 60-day warning horizon",
            "escalate",
            "V-EXP-002",
            True,
        ),
        (
            "unapproved_issuer",
            "Certification body not listed in official accredited registry",
            "fail",
            "V-ISS-001",
            False,
        ),
        (
            "fuzzy_issuer",
            "Typo in certification body name requiring human resolution",
            "escalate",
            "V-ISS-002",
            True,
        ),
        (
            "scope_mismatch",
            "BOM requests organic cotton but certificate covers recycled polyester only",
            "fail",
            "V-SCOPE-001",
            True,
        ),
        (
            "xdoc_supplier_mismatch",
            "Supplier ID in invoice does not match certificate supplier ID",
            "fail",
            "V-XDOC-001",
            False,
        ),
        (
            "missing_page",
            "Document indicates 'Page 1 of 3' but only 1 page provided",
            "escalate",
            "V-PAGE-001",
            True,
        ),
    ]

    for idx in range(num_cases):
        sc_type, sc_desc, expected_outcome, rule_id, must_escalate = scenario_types[
            idx % len(scenario_types)
        ]
        case_id = f"GOLDEN-{idx + 1:03d}"
        doc_id = f"DOC-GOLDEN-{idx + 1:03d}"
        doc_hash = f"hash_{idx + 1:03d}_{doc_id.lower()}_sha256"

        assessment_date = "2026-11-02"
        factory_id = f"FACT-{(idx % 50) + 1:04d}"
        supplier_id = f"SUP-{(idx % 30) + 1:03d}"

        if sc_type == "clean_pass":
            valid_from = "2024-01-01"
            valid_to = "2027-12-31"
            issuer = "Control Union Certifications B.V."
            cert_scope = "100% Organic Cotton"
            bom_material = "100% Organic Cotton"
            supplier_id_doc2 = supplier_id
            page_count = 1
        elif sc_type == "expired_cert":
            valid_from = "2023-01-01"
            valid_to = "2025-06-30"  # Expired
            issuer = "Ecocert Greenlife S.A.S."
            cert_scope = "100% Organic Cotton"
            bom_material = "100% Organic Cotton"
            supplier_id_doc2 = supplier_id
            page_count = 1
        elif sc_type == "near_expiry":
            valid_from = "2024-01-01"
            valid_to = "2026-11-20"  # Expiring in 18 days (< 60 days warn)
            issuer = "Control Union Certifications B.V."
            cert_scope = "100% Organic Cotton"
            bom_material = "100% Organic Cotton"
            supplier_id_doc2 = supplier_id
            page_count = 1
        elif sc_type == "unapproved_issuer":
            valid_from = "2024-01-01"
            valid_to = "2028-12-31"
            issuer = "Unverified Global Textile Certifiers Ltd"
            cert_scope = "100% Organic Cotton"
            bom_material = "100% Organic Cotton"
            supplier_id_doc2 = supplier_id
            page_count = 1
        elif sc_type == "fuzzy_issuer":
            valid_from = "2024-01-01"
            valid_to = "2028-12-31"
            issuer = "Control Union Certs B.V."  # Deliberately inside the fuzzy-review band.
            cert_scope = "100% Organic Cotton"
            bom_material = "100% Organic Cotton"
            supplier_id_doc2 = supplier_id
            page_count = 1
        elif sc_type == "scope_mismatch":
            valid_from = "2024-01-01"
            valid_to = "2028-12-31"
            issuer = "OEKO-TEX Association (Service GmbH)"
            cert_scope = "100% Recycled Polyester"
            bom_material = "100% Organic Cotton"
            supplier_id_doc2 = supplier_id
            page_count = 1
        elif sc_type == "xdoc_supplier_mismatch":
            valid_from = "2024-01-01"
            valid_to = "2028-12-31"
            issuer = "Control Union Certifications B.V."
            cert_scope = "100% Organic Cotton"
            bom_material = "100% Organic Cotton"
            supplier_id_doc2 = f"SUP-DIFFERENT-{idx:03d}"
            page_count = 1
        elif sc_type == "missing_page":
            valid_from = "2024-01-01"
            valid_to = "2028-12-31"
            issuer = "Control Union Certifications B.V."
            cert_scope = "100% Organic Cotton"
            bom_material = "100% Organic Cotton"
            supplier_id_doc2 = supplier_id
            page_count = 1  # But document text claims "Page 1 of 3"

        cases.append(
            {
                "case_id": case_id,
                "scenario": sc_type,
                "description": sc_desc,
                "assessment_date": assessment_date,
                "factory_id": factory_id,
                "documents": [
                    {
                        "doc_id": doc_id,
                        "doc_hash": doc_hash,
                        "doc_type": "certificate",
                        "fields": {
                            "issuer": issuer,
                            "valid_from": valid_from,
                            "valid_to": valid_to,
                            "scope_materials": cert_scope,
                            "facility_id": factory_id,
                            "supplier_id": supplier_id,
                            "page_claims": "Page 1 of 3"
                            if sc_type == "missing_page"
                            else "Page 1 of 1",
                        },
                        "page_count": page_count,
                    },
                    {
                        "doc_id": f"{doc_id}-BOM",
                        "doc_hash": f"{doc_hash}_bom",
                        "doc_type": "bom",
                        "fields": {
                            "materials": [bom_material],
                            "facility_id": factory_id,
                            "supplier_id": supplier_id_doc2,
                        },
                        "page_count": 1,
                    },
                ],
                "expected_verdicts": [
                    {
                        "rule_id": rule_id,
                        "expected_outcome": expected_outcome,
                    }
                ],
                "expected_escalation": must_escalate,
                "expected_overall_status": "compliant"
                if expected_outcome == "pass" and not must_escalate
                else (
                    "review_required"
                    if must_escalate or expected_outcome == "escalate"
                    else "non_compliant"
                ),
            }
        )

    with open(GOLDEN_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generator_version": "1.0.0",
                "seed": seed,
                "total_cases": len(cases),
                "cases": cases,
            },
            f,
            indent=2,
        )

    print(f"Generated {len(cases)} labeled golden set test cases at {GOLDEN_FILE}")
    return GOLDEN_FILE


if __name__ == "__main__":
    generate_golden_set()
