"""Boundary and determinism tests for deterministic verifier rules."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import pytest

from backend.app.domain.models import (
    Claim,
    ExternalLookup,
    SanctionsMatch,
    Verdict,
    VerificationContext,
)
from backend.app.integrations.base import LookupQuery, SnapshotRecord
from backend.app.integrations.fakes import FakeProvider
from backend.app.verifier.engine import Verifier, VerifierSettings, load_verifier_settings
from backend.app.verifier.registry_loader import load_approved_issuers
from backend.app.verifier.rules import (
    v_conf_001,
    v_date_001,
    v_exp_001,
    v_exp_002,
    v_ext_001,
    v_ext_002,
    v_ext_003,
    v_ext_900,
    v_iss_001,
    v_iss_002,
    v_page_001,
    v_sanc_001,
    v_sanc_002,
    v_scope_001,
    v_scope_002,
    v_xdoc_001,
    v_xdoc_002,
)

_CLAIM_ID = "claim-001"
_EVIDENCE_IDS = ["evidence-001"]
_MATCH_TYPES = Literal["exact_id", "exact_name", "fuzzy_name", "none"]


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
    unparsable = v_date_001.check(
        None,
        None,
        claim_id=_CLAIM_ID,
        evidence_ids=_EVIDENCE_IDS,
        unparsable=True,
    )
    _assert_result(unparsable, "V-DATE-001", "escalate", "VALIDITY_DATE_UNPARSABLE")


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
    registry = {"control union certifications b.v.": "Control Union Certifications B.V."}
    missing = v_iss_001.check(None, registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS)
    unknown = v_iss_001.check(
        "Unlisted issuer", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    approved = v_iss_001.check(
        " CONTROL UNION CERTIFICATIONS B.V. ", registry,
        claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )

    _assert_result(missing, "V-ISS-001", "escalate", "ISSUER_NAME_MISSING")
    _assert_result(unknown, "V-ISS-001", "fail", "ISSUER_NOT_APPROVED")
    _assert_result(approved, "V-ISS-001", "pass", "ISSUER_APPROVED")
    possible_match = v_iss_001.check(
        "Control Union Certs B.V.", registry,
        claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    _assert_result(possible_match, "V-ISS-001", "escalate", "ISSUER_POSSIBLE_FUZZY_MATCH")
    high_confidence = v_iss_001.check(
        "Control Union Certification B.V.", registry,
        claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    _assert_result(high_confidence, "V-ISS-001", "pass", "ISSUER_HIGH_CONFIDENCE_MATCH")
    with pytest.raises(ValueError, match="ordered"):
        v_iss_001.check(
            "unknown", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
            fail_below=0.9, review_through=0.75,
        )


def test_v_iss_002_exact_fuzzy_and_uncertain_matches() -> None:
    registry = {"control union": "Control Union"}
    missing = v_iss_002.check(None, registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS)
    exact = v_iss_002.check(
        "Control Union", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    fuzzy = v_iss_002.check("Control unity", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS)
    uncertain = v_iss_002.check(
        "Unrelated issuer", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )

    _assert_result(missing, "V-ISS-002", "escalate", "ISSUER_NAME_MISSING")
    _assert_result(exact, "V-ISS-002", "pass", "ISSUER_EXACT_MATCH")
    _assert_result(fuzzy, "V-ISS-002", "escalate", "ISSUER_FUZZY_MATCH_UNCERTAIN")
    _assert_result(uncertain, "V-ISS-002", "pass", "ISSUER_FUZZY_MATCH_ACCEPTED")
    assert uncertain == v_iss_002.check(
        "Unrelated issuer", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    empty_registry = v_iss_002.check(
        "Unrelated issuer", {}, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    _assert_result(
        empty_registry, "V-ISS-002", "pass", "ISSUER_FUZZY_MATCH_ACCEPTED"
    )
    with pytest.raises(ValueError, match="ordered"):
        v_iss_002.check(
            "unknown", registry, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
            review_min=0.9, review_max=0.75,
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
    _assert_result(unusable, "V-SCOPE-002", "escalate", "FACILITY_ID_MISSING")
    _assert_result(mismatch, "V-SCOPE-002", "fail", "FACILITY_ID_MISMATCH")
    _assert_result(matching, "V-SCOPE-002", "pass", "FACILITY_ID_MATCH")
    name_only = v_scope_002.check(
        None,
        None,
        claim_id=_CLAIM_ID,
        evidence_ids=_EVIDENCE_IDS,
        cert_facility_name="Mill 1",
        bom_facility_name="Mill 2",
    )
    _assert_result(name_only, "V-SCOPE-002", "escalate", "FACILITY_NAME_MISMATCH")


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
    _assert_result(conflicting, "V-XDOC-002", "escalate", "CROSS_DOCUMENT_MATERIAL_CONFLICT")
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


def _external_lookup(
    *,
    status: str = "healthy",
    matched: bool = True,
    match_type: _MATCH_TYPES = "exact_id",
    score: float = 1.0,
    fetched_at: date = date(2026, 11, 1),
    snapshot_hash: str | None = "snapshot-1",
    country_match: bool | None = True,
    parent_company_match: bool | None = True,
) -> ExternalLookup:
    from datetime import datetime, time

    return ExternalLookup(
        source="facility-snapshot",
        status=status,
        matched=matched,
        match_type=match_type,
        score=score,
        record_key="record-1" if matched else None,
        fetched_at=datetime.combine(fetched_at, time.min, tzinfo=UTC),
        snapshot_hash=snapshot_hash,
        country_match=country_match,
        parent_company_match=parent_company_match,
    )


def test_v_page_001_missing_unreadable_mismatch_gap_duplicate_and_valid() -> None:
    missing = v_page_001.check(
        None, 1, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    not_claimed = v_page_001.check(
        [], 1, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    unreadable = v_page_001.check(
        ["Page unknown"], 1, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    mismatch = v_page_001.check(
        ["Page 1 of 3"], 1, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    gap = v_page_001.check(
        ["Page 1 of 3", "Page 3 of 3"],
        3,
        claim_id=_CLAIM_ID,
        evidence_ids=_EVIDENCE_IDS,
    )
    duplicate = v_page_001.check(
        ["Page 1 of 2", "Page 1 of 2"],
        2,
        claim_id=_CLAIM_ID,
        evidence_ids=_EVIDENCE_IDS,
    )
    valid = v_page_001.check(
        ["Page 1 of 2", "Page 2 of 2"],
        2,
        claim_id=_CLAIM_ID,
        evidence_ids=_EVIDENCE_IDS,
    )

    _assert_result(missing, "V-PAGE-001", "escalate", "PAGE_COUNT_EVIDENCE_MISSING")
    _assert_result(not_claimed, "V-PAGE-001", "pass", "PAGE_NUMBERING_NOT_PRESENT")
    _assert_result(unreadable, "V-PAGE-001", "escalate", "PAGE_NUMBERING_UNREADABLE")
    _assert_result(mismatch, "V-PAGE-001", "escalate", "PAGE_COUNT_MISMATCH")
    _assert_result(gap, "V-PAGE-001", "escalate", "PAGE_COUNT_MISMATCH")
    _assert_result(duplicate, "V-PAGE-001", "escalate", "PAGE_COUNT_MISMATCH")
    _assert_result(valid, "V-PAGE-001", "pass", "PAGE_COUNT_MATCH")


def test_v_conf_001_risk_adjusted_thresholds_and_validation() -> None:
    def check(confidence: float, risk: float) -> Verdict:
        return v_conf_001.check(
            confidence,
            risk,
            0.85,
            0.90,
            0.95,
            0.30,
            0.60,
            claim_id=_CLAIM_ID,
            evidence_ids=_EVIDENCE_IDS,
        )

    _assert_result(
        check(0.84, 0.0),
        "V-CONF-001",
        "escalate",
        "EXTRACTION_CONFIDENCE_BELOW_THRESHOLD",
    )
    _assert_result(
        check(0.90, 0.30),
        "V-CONF-001",
        "pass",
        "EXTRACTION_CONFIDENCE_ACCEPTED",
    )
    _assert_result(
        check(0.94, 0.60),
        "V-CONF-001",
        "escalate",
        "EXTRACTION_CONFIDENCE_BELOW_THRESHOLD",
    )
    critical = check(0.94, 0.60)
    assert critical.details["priority"] == "critical"
    with pytest.raises(ValueError, match="between 0 and 1"):
        v_conf_001.check(
            1.1, 0.0, 0.85, 0.9, 0.95, 0.3, 0.6,
            claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
        )
    with pytest.raises(ValueError, match="must not exceed"):
        v_conf_001.check(
            0.9, 0.0, 0.85, 0.9, 0.95, 0.7, 0.6,
            claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
        )


def test_v_ext_001_identity_match_conflict_ambiguity_and_missing() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        v_ext_001.check(
            _external_lookup(),
            claim_id=_CLAIM_ID,
            evidence_ids=_EVIDENCE_IDS,
            not_found_threshold=1.1,
        )
    _assert_result(
        v_ext_001.check(None, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS),
        "V-EXT-001",
        "escalate",
        "EXTERNAL_FACILITY_SOURCE_UNAVAILABLE",
    )
    _assert_result(
        v_ext_001.check(_external_lookup(), claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS),
        "V-EXT-001",
        "pass",
        "EXTERNAL_FACILITY_MATCH",
    )
    unmatched = v_ext_001.check(
        _external_lookup(matched=False, match_type="exact_id", score=0.0),
        claim_id=_CLAIM_ID,
        evidence_ids=_EVIDENCE_IDS,
    )
    _assert_result(unmatched, "V-EXT-001", "escalate", "EXTERNAL_FACILITY_NOT_FOUND")
    _assert_result(
        v_ext_001.check(
            _external_lookup(match_type="fuzzy_name", score=0.74),
            claim_id=_CLAIM_ID,
            evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-001",
        "escalate",
        "EXTERNAL_FACILITY_NOT_FOUND",
    )
    _assert_result(
        v_ext_001.check(
            _external_lookup(match_type="fuzzy_name", score=0.8),
            claim_id=_CLAIM_ID,
            evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-001",
        "pass",
        "EXTERNAL_FACILITY_CANDIDATE_FOUND",
    )
    _assert_result(
        v_ext_001.check(
            _external_lookup(status="unavailable"),
            claim_id=_CLAIM_ID,
            evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-001",
        "escalate",
        "EXTERNAL_FACILITY_SOURCE_UNAVAILABLE",
    )


def test_v_ext_002_country_and_name_match_thresholds() -> None:
    _assert_result(
        v_ext_002.check(
            None, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
        ),
        "V-EXT-002",
        "escalate",
        "EXTERNAL_FACILITY_DATA_UNAVAILABLE",
    )
    _assert_result(
        v_ext_002.check(
            _external_lookup(matched=False, match_type="none"),
            claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-002",
        "pass",
        "EXTERNAL_FACILITY_MATCH_NOT_APPLICABLE",
    )
    _assert_result(
        v_ext_002.check(
            _external_lookup(country_match=False),
            claim_id=_CLAIM_ID,
            evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-002",
        "escalate",
        "EXTERNAL_FACILITY_COUNTRY_MISMATCH",
    )
    _assert_result(
        v_ext_002.check(
            _external_lookup(country_match=None),
            claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-002",
        "escalate",
        "EXTERNAL_FACILITY_COUNTRY_UNVERIFIED",
    )
    for score in (0.75, 0.90):
        _assert_result(
            v_ext_002.check(
                _external_lookup(match_type="fuzzy_name", score=score),
                claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
            ),
            "V-EXT-002",
            "escalate",
            "EXTERNAL_FACILITY_NAME_AMBIGUOUS",
        )
    _assert_result(
        v_ext_002.check(
            _external_lookup(match_type="fuzzy_name", score=0.91),
            claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-002",
        "pass",
        "EXTERNAL_FACILITY_COUNTRY_AND_NAME_CONFIRMED",
    )
    with pytest.raises(ValueError, match="review thresholds"):
        v_ext_002.check(
            _external_lookup(), claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
            name_review_min=0.91, name_review_max=0.90,
        )


def test_v_ext_003_parent_company_relationship() -> None:
    _assert_result(
        v_ext_003.check(None, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS),
        "V-EXT-003",
        "escalate",
        "EXTERNAL_PARENT_COMPANY_UNVERIFIED",
    )
    _assert_result(
        v_ext_003.check(
            _external_lookup(parent_company_match=False),
            claim_id=_CLAIM_ID,
            evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-003",
        "escalate",
        "EXTERNAL_PARENT_COMPANY_MISMATCH",
    )
    _assert_result(
        v_ext_003.check(
            _external_lookup(parent_company_match=None),
            claim_id=_CLAIM_ID,
            evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-003",
        "escalate",
        "EXTERNAL_PARENT_COMPANY_UNVERIFIED",
    )
    _assert_result(
        v_ext_003.check(
            _external_lookup(parent_company_match=True),
            claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-003",
        "pass",
        "EXTERNAL_PARENT_COMPANY_CONFIRMED",
    )


def test_v_ext_900_snapshot_freshness_and_provider_availability() -> None:
    assessment = date(2026, 11, 2)
    for lookup in (None, _external_lookup(status="unavailable"), _external_lookup(status="degraded")):
        _assert_result(
            v_ext_900.check(
                lookup, assessment, 30, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
            ),
            "V-EXT-900",
            "escalate",
            "EXTERNAL_SOURCE_UNAVAILABLE",
        )
    _assert_result(
        v_ext_900.check(
            _external_lookup(fetched_at=date(2026, 10, 3)),
            assessment, 30, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
        ),
        "V-EXT-900",
        "pass",
        "EXTERNAL_SNAPSHOT_FRESH",
    )
    for fetched_at in (date(2026, 10, 2), date(2026, 11, 3)):
        _assert_result(
            v_ext_900.check(
                _external_lookup(fetched_at=fetched_at),
                assessment, 30, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
            ),
            "V-EXT-900",
            "escalate",
            "EXTERNAL_SNAPSHOT_STALE",
        )
    with pytest.raises(ValueError, match="non-negative"):
        v_ext_900.check(
            _external_lookup(), assessment, -1,
            claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
        )


def test_v_sanc_001_only_exact_identifier_match_fails_critically() -> None:
    _assert_result(
        v_sanc_001.check(None, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS),
        "V-SANC-001",
        "escalate",
        "SANCTIONS_EVIDENCE_MISSING",
    )
    match = SanctionsMatch(
        source="sanctions-fixture",
        matched=True,
        match_type="exact_id",
        score=1.0,
        record_key="list-1",
        snapshot_hash="sha256:fixture",
    )
    verdict = v_sanc_001.check(
        [match], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    _assert_result(verdict, "V-SANC-001", "fail", "SANCTIONS_EXACT_MATCH")
    assert verdict.details["priority"] == "critical"
    exact_name = SanctionsMatch(
        source="sanctions-fixture",
        matched=True,
        match_type="exact_name",
        score=1.0,
        record_key="list-2",
        snapshot_hash="sha256:fixture",
    )
    _assert_result(
        v_sanc_001.check(
            [exact_name], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
        ),
        "V-SANC-001",
        "pass",
        "SANCTIONS_EXACT_MATCH_NOT_FOUND",
    )


def test_v_sanc_002_name_only_and_high_confidence_fuzzy_matches_escalate() -> None:
    match = SanctionsMatch(
        source="sanctions-fixture",
        matched=True,
        match_type="fuzzy_name",
        score=0.9,
        record_key="list-2",
        snapshot_hash="sha256:fixture",
    )
    verdict = v_sanc_002.check(
        [match], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    _assert_result(verdict, "V-SANC-002", "escalate", "SANCTIONS_POSSIBLE_FUZZY_MATCH")
    assert verdict.details["priority"] == "critical"
    exact_name = match.model_copy(update={"match_type": "exact_name", "score": 1.0})
    exact_name_verdict = v_sanc_002.check(
        [exact_name], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
    )
    _assert_result(
        exact_name_verdict, "V-SANC-002", "escalate", "SANCTIONS_POSSIBLE_FUZZY_MATCH"
    )
    assert exact_name_verdict.details["priority"] == "critical"
    below_threshold = match.model_copy(update={"score": 0.89})
    _assert_result(
        v_sanc_002.check(
            [below_threshold], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
        ),
        "V-SANC-002",
        "pass",
        "SANCTIONS_FUZZY_MATCH_NOT_FOUND",
    )
    _assert_result(
        v_sanc_002.check(
            None, claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS
        ),
        "V-SANC-002",
        "escalate",
        "SANCTIONS_EVIDENCE_MISSING",
    )
    with pytest.raises(ValueError, match="between 0 and 1"):
        v_sanc_002.check(
            [], claim_id=_CLAIM_ID, evidence_ids=_EVIDENCE_IDS,
            review_threshold=1.1,
        )


def test_provider_fake_requires_refresh_and_returns_snapshot_records() -> None:
    record = SnapshotRecord(
        record_key="r1",
        normalized_name="mill one",
        country="BD",
        identifiers={"facility_id": "FAC-1"},
    )
    provider = FakeProvider(records=[record])
    with pytest.raises(RuntimeError, match="refreshed"):
        provider.lookup(LookupQuery(name="mill one"))
    snapshot = provider.refresh()
    assert snapshot.snapshot_hash == "fake:fake:snapshot-v1"
    assert provider.lookup(LookupQuery(name="MILL ONE", country="bd")) == [record]
    assert provider.health().available
    unavailable = FakeProvider(unavailable=True)
    assert not unavailable.health().available
    with pytest.raises(RuntimeError, match="unavailable"):
        unavailable.refresh()


def test_verifier_engine_is_deterministic_links_evidence_and_derives_priority() -> None:
    settings = load_verifier_settings()
    claim = Claim(
        claim_id=_CLAIM_ID,
        claim_text="Certificate compliance",
        doc_id="cert-1",
        doc_hash="hash-1",
        page=1,
        extractor_confidence=0.80,
        evidence_ids=_EVIDENCE_IDS,
    )
    context = VerificationContext(
        assessment_date=date(2026, 11, 2),
        fields_by_claim={
            _CLAIM_ID: {
                "valid_from": "2024-01-01",
                "valid_to": "2025-01-01",
                "issuer": "Unknown issuer",
            }
        },
        page_claims_by_doc={"cert-1": ["Page 1 of 2"]},
        page_counts_by_doc={"cert-1": 1},
        supplier_ids_by_doc={"cert-1": "SUP-1", "bom-1": "SUP-2"},
        materials_by_doc={"cert-1": ["cotton"], "bom-1": ["wool"]},
        certificate_doc_by_claim={_CLAIM_ID: "cert-1"},
        bom_doc_by_claim={_CLAIM_ID: "bom-1"},
        external_lookups_by_claim={
            _CLAIM_ID: _external_lookup(status="unavailable")
        },
        sanctions_matches_by_claim={
            _CLAIM_ID: [
                SanctionsMatch(
                    source="test-list",
                    matched=True,
                    match_type="fuzzy_name",
                    score=0.95,
                    snapshot_hash="test-hash",
                )
            ]
        },
    )
    verifier = Verifier(
        registry={"approved issuer": "Approved issuer"},
        settings=settings,
    )
    verdicts = verifier.verify([claim], context)
    assert verdicts == verifier.verify([claim], context)
    assert all(verdict.claim_id == claim.claim_id for verdict in verdicts)
    assert all(verdict.evidence_ids == _EVIDENCE_IDS for verdict in verdicts)
    ids = {verdict.rule_id for verdict in verdicts}
    assert {
        "V-DATE-001", "V-EXP-001", "V-EXP-002", "V-ISS-001", "V-ISS-002",
        "V-SCOPE-001", "V-SCOPE-002", "V-XDOC-001", "V-XDOC-002",
        "V-CONF-001", "V-PAGE-001", "V-EXT-001", "V-EXT-002",
        "V-EXT-003", "V-EXT-900", "V-SANC-001", "V-SANC-002",
    }.issubset(ids)
    escalation = verifier.escalation_state(verdicts, context.risk_score)
    assert escalation.is_escalated
    assert escalation.priority == "critical"
    assert escalation.triggered_by_rule is not None

    missing_evidence = claim.model_copy(update={"evidence_ids": []})
    with pytest.raises(ValueError, match="no evidence IDs"):
        verifier.verify([missing_evidence], context)


def test_verifier_engine_unparsable_dates_and_escalation_validation() -> None:
    claim = Claim(
        claim_id=_CLAIM_ID,
        claim_text="Certificate",
        doc_id="cert-1",
        doc_hash="hash-1",
        page=1,
        extractor_confidence=0.99,
        evidence_ids=_EVIDENCE_IDS,
    )
    context = VerificationContext(
        assessment_date=date(2026, 11, 2),
        fields_by_claim={
            _CLAIM_ID: {"valid_from": "not-a-date", "valid_to": "2027-01-01"}
        },
    )
    verifier = Verifier(registry={"approved issuer": "Approved issuer"})
    verdicts = verifier.verify([claim], context)
    assert verdicts[0].reason_code == "VALIDITY_DATE_UNPARSABLE"
    with pytest.raises(ValueError, match="between 0 and 1"):
        verifier.escalation_state(verdicts, 1.1)
    invalid_shape = VerificationContext(
        assessment_date=date(2026, 11, 2),
        fields_by_claim={_CLAIM_ID: {"valid_from": 123, "valid_to": date(2027, 1, 1)}},
    )
    assert verifier.verify([claim], invalid_shape)[0].reason_code == "VALIDITY_DATE_MISSING"


def test_verifier_engine_accepts_date_objects_and_string_scope() -> None:
    claim = Claim(
        claim_id=_CLAIM_ID,
        claim_text="Certificate",
        doc_id="cert-1",
        doc_hash="hash-1",
        page=1,
        extractor_confidence=0.99,
        evidence_ids=_EVIDENCE_IDS,
    )
    context = VerificationContext(
        assessment_date=date(2026, 11, 2),
        fields_by_claim={
            _CLAIM_ID: {
                "valid_from": date(2024, 1, 1),
                "valid_to": datetime(2027, 1, 1, tzinfo=UTC),
                "scope_materials": "organic cotton",
            }
        },
    )
    verifier = Verifier(registry={"approved issuer": "Approved issuer"})
    assert verifier.verify([claim], context)[0].reason_code == "VALIDITY_DATE_RANGE_VALID"


def test_verifier_settings_reject_incomplete_configuration(tmp_path: Path) -> None:
    settings = VerifierSettings.from_mapping(
        {
            "warnings": {"expiry_days": 60, "snapshot_max_age_days": 30},
            "confidence": {"base": 0.85, "moderate_risk": 0.9, "high_risk": 0.95},
            "risk": {"moderate_threshold": 0.3, "high_threshold": 0.6},
            "issuer": {"fail_below": 0.75, "escalate_through": 0.9},
            "external": {"review_min": 0.75, "review_max": 0.90},
            "sanctions": {"fuzzy_review": 0.90},
        }
    )
    assert settings.expiry_warn_days == 60
    invalid_thresholds = settings.model_dump()
    invalid_thresholds["confidence_base"] = 0.91
    with pytest.raises(ValueError, match="confidence thresholds"):
        VerifierSettings.model_validate(invalid_thresholds)
    invalid_thresholds = settings.model_dump()
    invalid_thresholds["risk_moderate_threshold"] = 0.7
    with pytest.raises(ValueError, match="risk thresholds"):
        VerifierSettings.model_validate(invalid_thresholds)
    invalid_thresholds = settings.model_dump()
    invalid_thresholds["issuer_fail_below"] = 0.95
    with pytest.raises(ValueError, match="issuer thresholds"):
        VerifierSettings.model_validate(invalid_thresholds)
    invalid_thresholds = settings.model_dump()
    invalid_thresholds["external_name_review_min"] = 0.95
    with pytest.raises(ValueError, match="external name review thresholds"):
        VerifierSettings.model_validate(invalid_thresholds)
    config_path = tmp_path / "empty.yaml"
    config_path.write_text("[]", encoding="utf-8")
    from backend.app.verifier.engine import load_verifier_settings

    with pytest.raises(ValueError, match="must be a mapping"):
        load_verifier_settings(config_path)
    with pytest.raises(ValueError, match="incomplete"):
        VerifierSettings.from_mapping({})
