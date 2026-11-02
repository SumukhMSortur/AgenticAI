"""Boundary and determinism tests for deterministic verifier rules."""

from datetime import date
from pathlib import Path

import pytest

from backend.app.domain.models import Verdict
from backend.app.verifier.registry_loader import load_approved_issuers
from backend.app.verifier.rules import (
    v_date_001,
    v_exp_001,
    v_exp_002,
    v_iss_001,
    v_iss_002,
    v_scope_001,
    v_scope_002,
    v_xdoc_001,
    v_xdoc_002,
)

_CLAIM_ID = "claim-001"
_EVIDENCE_IDS = ["evidence-001"]


def _assert_result(verdict: Verdict, rule_id: str, outcome: str, reason_code: str) -> None:
    assert verdict.claim_id == _CLAIM_ID
    assert verdict.rule_id == rule_id
    assert verdict.outcome == outcome
    assert verdict.reason_code == reason_code
    assert verdict.evidence_ids == _EVIDENCE_IDS
    assert isinstance(verdict.details, dict)


def test_v_date_001_missing_invalid_and_valid_ranges() -> None:
    missing = v_date_001.check(
        None, date(2027, 1, 1), claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    invalid = v_date_001.check(
        date(2027, 1, 2), date(2027, 1, 1), claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    valid = v_date_001.check(
        date(2027, 1, 1), date(2027, 1, 1), claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )

    _assert_result(missing, "V-DATE-001", "escalate", "VALIDITY_DATE_MISSING")
    _assert_result(invalid, "V-DATE-001", "escalate", "VALIDITY_DATE_RANGE_INVALID")
    _assert_result(valid, "V-DATE-001", "pass", "VALIDITY_DATE_RANGE_VALID")
    assert invalid == v_date_001.check(
        date(2027, 1, 2), date(2027, 1, 1), claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )


def test_v_exp_001_missing_expired_and_expiry_boundary() -> None:
    missing = v_exp_001.check(
        None, date(2027, 1, 1), claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    expired = v_exp_001.check(
        date(2026, 12, 31), date(2027, 1, 1), claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    active_on_boundary = v_exp_001.check(
        date(2027, 1, 1), date(2027, 1, 1), claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )

    _assert_result(missing, "V-EXP-001", "escalate", "EXPIRY_DATE_MISSING")
    _assert_result(expired, "V-EXP-001", "fail", "CERTIFICATE_EXPIRED")
    _assert_result(active_on_boundary, "V-EXP-001", "pass", "CERTIFICATE_NOT_EXPIRED")


def test_v_exp_002_warning_window_boundaries_and_invalid_config() -> None:
    missing = v_exp_002.check(
        None, date(2027, 1, 1), 60, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    in_window = v_exp_002.check(
        date(2027, 3, 2), date(2027, 1, 1), 60, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    out_of_window = v_exp_002.check(
        date(2027, 3, 3), date(2027, 1, 1), 60, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )

    _assert_result(missing, "V-EXP-002", "escalate", "EXPIRY_WARNING_DATE_MISSING")
    _assert_result(in_window, "V-EXP-002", "escalate", "CERTIFICATE_NEAR_EXPIRY")
    _assert_result(out_of_window, "V-EXP-002", "pass", "CERTIFICATE_OUTSIDE_EXPIRY_WARNING")
    with pytest.raises(ValueError, match="non-negative"):
        v_exp_002.check(
            date(2027, 1, 2),
            date(2027, 1, 1),
            -1,
            claim_id=_CLAIM_ID,
            evidence_ids=_EVIDENCE_IDS,
        )


def test_v_iss_001_exact_registry_membership() -> None:
    registry = {"control union": "Control Union"}
    missing = v_iss_001.check(None, registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS)
    unknown = v_iss_001.check(
        "Unlisted issuer", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    approved = v_iss_001.check(
        " CONTROL UNION ", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )

    _assert_result(missing, "V-ISS-001", "escalate", "ISSUER_NAME_MISSING")
    _assert_result(unknown, "V-ISS-001", "fail", "ISSUER_NOT_APPROVED")
    _assert_result(approved, "V-ISS-001", "pass", "ISSUER_APPROVED")


def test_v_iss_002_exact_fuzzy_and_uncertain_matches() -> None:
    registry = {"control union": "Control Union"}
    missing = v_iss_002.check(None, registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS)
    exact = v_iss_002.check(
        "Control Union", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    fuzzy = v_iss_002.check(
        "Control Unio", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    uncertain = v_iss_002.check(
        "Unrelated issuer", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )

    _assert_result(missing, "V-ISS-002", "escalate", "ISSUER_NAME_MISSING")
    _assert_result(exact, "V-ISS-002", "pass", "ISSUER_EXACT_MATCH")
    _assert_result(fuzzy, "V-ISS-002", "pass", "ISSUER_FUZZY_MATCH_ACCEPTED")
    _assert_result(uncertain, "V-ISS-002", "escalate", "ISSUER_FUZZY_MATCH_UNCERTAIN")
    assert uncertain == v_iss_002.check(
        "Unrelated issuer", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    empty_registry = v_iss_002.check(
        "Unrelated issuer", {}, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    _assert_result(
        empty_registry, "V-ISS-002", "escalate", "ISSUER_FUZZY_MATCH_UNCERTAIN"
    )


def test_v_scope_001_missing_unusable_mismatched_and_overlapping_materials() -> None:
    missing = v_scope_001.check(
        None, ["cotton"], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    unusable = v_scope_001.check(
        [" "], ["cotton"], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    mismatch = v_scope_001.check(
        ["wool"], ["cotton"], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    overlap = v_scope_001.check(
        ["Cotton", "Wool"], ["cotton"], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )

    _assert_result(missing, "V-SCOPE-001", "escalate", "MATERIAL_SCOPE_MISSING")
    _assert_result(unusable, "V-SCOPE-001", "escalate", "MATERIAL_SCOPE_UNREADABLE")
    _assert_result(mismatch, "V-SCOPE-001", "fail", "MATERIAL_SCOPE_MISMATCH")
    _assert_result(overlap, "V-SCOPE-001", "pass", "MATERIAL_SCOPE_MATCH")
    assert overlap == v_scope_001.check(
        ["Cotton", "Wool"], ["cotton"], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )


def test_v_scope_002_missing_unusable_mismatched_and_matching_ids() -> None:
    missing = v_scope_002.check(
        None, "FAC-001", claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    unusable = v_scope_002.check(
        " ", "FAC-001", claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    mismatch = v_scope_002.check(
        "FAC-001", "FAC-002", claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    matching = v_scope_002.check(
        "fac-001", "FAC-001", claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )

    _assert_result(missing, "V-SCOPE-002", "escalate", "FACILITY_ID_MISSING")
    _assert_result(unusable, "V-SCOPE-002", "escalate", "FACILITY_ID_UNREADABLE")
    _assert_result(mismatch, "V-SCOPE-002", "fail", "FACILITY_ID_MISMATCH")
    _assert_result(matching, "V-SCOPE-002", "pass", "FACILITY_ID_MATCH")


def test_v_xdoc_001_missing_unusable_conflicting_and_consistent_ids() -> None:
    missing = v_xdoc_001.check(
        None, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    unusable = v_xdoc_001.check(
        [" ", ""], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    conflicting = v_xdoc_001.check(
        ["SUP-001", "SUP-002"], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    consistent = v_xdoc_001.check(
        ["SUP-001", " sup-001 "], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )

    _assert_result(missing, "V-XDOC-001", "escalate", "SUPPLIER_IDS_MISSING")
    _assert_result(unusable, "V-XDOC-001", "escalate", "SUPPLIER_IDS_UNREADABLE")
    _assert_result(conflicting, "V-XDOC-001", "fail", "SUPPLIER_ID_CONFLICT")
    _assert_result(consistent, "V-XDOC-001", "pass", "SUPPLIER_ID_CONSISTENT")


def test_v_xdoc_002_not_applicable_missing_conflicting_and_consistent_claims() -> None:
    not_applicable = v_xdoc_002.check(
        {"doc-1": ["cotton"]}, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    missing = v_xdoc_002.check(
        {"doc-1": ["cotton"], "doc-2": []},
        claim_id=_CLAIM_ID,
        evidence_ids=_EVIDENCE_IDS,
    )
    conflicting = v_xdoc_002.check(
        {"doc-1": ["cotton"], "doc-2": ["wool"]},
        claim_id=_CLAIM_ID,
        evidence_ids=_EVIDENCE_IDS,
    )
    consistent = v_xdoc_002.check(
        {"doc-1": ["cotton", "wool"], "doc-2": ["cotton"]},
        claim_id=_CLAIM_ID,
        evidence_ids=_EVIDENCE_IDS,
    )

    _assert_result(not_applicable, "V-XDOC-002", "pass", "CROSS_DOCUMENT_CHECK_NOT_APPLICABLE")
    _assert_result(missing, "V-XDOC-002", "escalate", "CROSS_DOCUMENT_MATERIALS_MISSING")
    _assert_result(conflicting, "V-XDOC-002", "fail", "CROSS_DOCUMENT_MATERIAL_CONFLICT")
    _assert_result(consistent, "V-XDOC-002", "pass", "CROSS_DOCUMENT_MATERIALS_CONSISTENT")


def test_mock_registry_loader_logs_banner_and_returns_active_issuers(caplog: pytest.LogCaptureFixture) -> None:
    registry = load_approved_issuers()

    assert registry["control union certifications b.v."] == "Control Union Certifications B.V."
    assert "MOCK issuer registry loaded" in caplog.text


def test_registry_loader_rejects_missing_path_and_invalid_header(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.csv"
    with pytest.raises(FileNotFoundError):
        load_approved_issuers(registry_path)

    registry_path.write_text("issuer_id,name\n", encoding="utf-8")
    with pytest.raises(ValueError, match="required columns"):
        load_approved_issuers(registry_path)


def test_registry_loader_rejects_incomplete_rows_and_empty_active_registry(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "registry.csv"
    header = "normalized_name,canonical_name,status,is_mock\n"
    registry_path.write_text(header + ",Incomplete,active,false\n", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete row"):
        load_approved_issuers(registry_path)

    registry_path.write_text(header + "inactive,Inactive issuer,revoked,false\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no active issuers"):
        load_approved_issuers(registry_path)
