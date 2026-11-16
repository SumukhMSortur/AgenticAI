"""Unit tests for Phase 4: Risk provenance, typed verdicts, and audit history importer."""

from backend.app.domain.models import RiskForecast, Verdict
from backend.app.risk.importer import AuditHistoryImporter


def test_verdict_typed_enum_and_provenance():
    verdict = Verdict(
        claim_id="claim_001",
        rule_id="V-DATE-001",
        outcome="pass",
        reason_code="VALIDITY_DATE_RANGE_VALID",
        rule_version="v1.0",
        snapshot_ref="snapshot_hash_12345",
    )
    assert verdict.outcome == "pass"
    assert verdict.rule_version == "v1.0"
    assert verdict.snapshot_ref == "snapshot_hash_12345"

    inconclusive_verdict = Verdict(
        claim_id="claim_002",
        rule_id="V-EXT-900",
        outcome="inconclusive",
        reason_code="REGISTRY_UNREACHABLE",
    )
    assert inconclusive_verdict.outcome == "inconclusive"


def test_risk_forecast_synthetic_provenance_tag():
    forecast = RiskForecast(
        factory_id="FAC-001",
        p_fail_6m=0.045,
        model_tag="xgboost",
        trained_on="synthetic",
    )
    assert forecast.trained_on == "synthetic"
    assert "trained on synthetic data" in forecast.disclaimer


def test_audit_history_csv_importer():
    sample_csv = """factory_id,audit_date,minor,major,critical,passed
FAC-999,2024-01-15,1,0,0,true
FAC-999,2024-06-20,0,1,0,false
"""
    result = AuditHistoryImporter.import_csv(sample_csv)
    assert "FAC-999" in result
    assert len(result["FAC-999"]) == 2
    assert result["FAC-999"][0]["non_compliances_minor"] == 1
    assert result["FAC-999"][1]["passed"] is False
