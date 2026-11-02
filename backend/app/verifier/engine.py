"""Deterministic orchestration for verifier rules."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from backend.app.domain.models import (
    Claim,
    EscalationState,
    Verdict,
    VerificationContext,
)
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

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "verifier.yaml"


class VerifierSettings(BaseModel):
    """Validated thresholds read outside the pure rule functions."""

    expiry_warn_days: int = Field(ge=0)
    snapshot_max_age_days: int = Field(ge=0)
    confidence_base: float = Field(ge=0.0, le=1.0)
    confidence_moderate_risk: float = Field(ge=0.0, le=1.0)
    confidence_high_risk: float = Field(ge=0.0, le=1.0)
    risk_moderate_threshold: float = Field(ge=0.0, le=1.0)
    risk_high_threshold: float = Field(ge=0.0, le=1.0)
    issuer_fail_below: float = Field(ge=0.0, le=1.0)
    issuer_escalate_through: float = Field(ge=0.0, le=1.0)
    external_confirmed_match: float = Field(ge=0.0, le=1.0)
    sanctions_fuzzy_review: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_ordered_thresholds(self) -> "VerifierSettings":
        """Reject contradictory thresholds before they affect rule outcomes."""
        if not (
            self.confidence_base
            <= self.confidence_moderate_risk
            <= self.confidence_high_risk
        ):
            raise ValueError("confidence thresholds must be nondecreasing")
        if self.risk_moderate_threshold > self.risk_high_threshold:
            raise ValueError("risk thresholds must be nondecreasing")
        if self.issuer_fail_below > self.issuer_escalate_through:
            raise ValueError("issuer thresholds must be nondecreasing")
        return self

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "VerifierSettings":
        """Flatten the reviewed YAML shape and validate every threshold."""
        try:
            flattened = {
                "expiry_warn_days": data["warnings"]["expiry_days"],
                "snapshot_max_age_days": data["warnings"]["snapshot_max_age_days"],
                "confidence_base": data["confidence"]["base"],
                "confidence_moderate_risk": data["confidence"]["moderate_risk"],
                "confidence_high_risk": data["confidence"]["high_risk"],
                "risk_moderate_threshold": data["risk"]["moderate_threshold"],
                "risk_high_threshold": data["risk"]["high_threshold"],
                "issuer_fail_below": data["issuer"]["fail_below"],
                "issuer_escalate_through": data["issuer"]["escalate_through"],
                "external_confirmed_match": data["external"]["confirmed_match"],
                "sanctions_fuzzy_review": data["sanctions"]["fuzzy_review"],
            }
        except (KeyError, TypeError) as error:
            raise ValueError(f"Verifier configuration is incomplete: {error}") from error
        return cls.model_validate(flattened)


def load_verifier_settings(path: Path = _CONFIG_PATH) -> VerifierSettings:
    """Read verifier thresholds from the checked-in YAML configuration."""
    with path.open(encoding="utf-8") as config_file:
        loaded = yaml.safe_load(config_file)
    if not isinstance(loaded, dict):
        raise ValueError(f"Verifier configuration must be a mapping: {path}")
    return VerifierSettings.from_mapping(loaded)


def _as_date(value: Any) -> date | None:
    """Parse only the date shapes accepted at the verifier boundary."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _is_unparsable_date(value: Any) -> bool:
    return isinstance(value, str) and _as_date(value) is None


def _as_strings(value: Any) -> list[str] | None:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return None


class Verifier:
    """Run pure rule functions on vault-mapped values and evidence references."""

    def __init__(
        self,
        registry: Mapping[str, str] | None = None,
        settings: VerifierSettings | None = None,
    ) -> None:
        self.registry = dict(registry) if registry is not None else load_approved_issuers()
        self.settings = settings or load_verifier_settings()

    def verify(
        self,
        claims: Sequence[Claim],
        context: VerificationContext,
    ) -> list[Verdict]:
        """Evaluate applicable deterministic rules in a stable claim/rule order."""
        results: list[Verdict] = []
        supplier_ids = context.supplier_ids_by_doc
        materials_by_doc = context.materials_by_doc
        for claim in sorted(claims, key=lambda item: item.claim_id):
            if not claim.evidence_ids:
                raise ValueError(f"Claim {claim.claim_id} has no evidence IDs")
            fields = context.fields_by_claim.get(claim.claim_id, {})
            valid_from = _as_date(fields.get("valid_from"))
            valid_to = _as_date(fields.get("valid_to"))
            invalid_date = _is_unparsable_date(fields.get("valid_from")) or _is_unparsable_date(
                fields.get("valid_to")
            )
            issuer_name = fields.get("issuer")
            issuer = issuer_name if isinstance(issuer_name, str) else None
            results.extend(
                [
                    v_date_001.check(
                        valid_from,
                        valid_to,
                        claim_id=claim.claim_id,
                        evidence_ids=claim.evidence_ids,
                        unparsable=invalid_date,
                    ),
                    v_exp_001.check(
                        valid_to,
                        context.assessment_date,
                        claim_id=claim.claim_id,
                        evidence_ids=claim.evidence_ids,
                    ),
                    v_exp_002.check(
                        valid_to,
                        context.assessment_date,
                        self.settings.expiry_warn_days,
                        claim_id=claim.claim_id,
                        evidence_ids=claim.evidence_ids,
                    ),
                    v_iss_001.check(
                        issuer,
                        self.registry,
                        claim_id=claim.claim_id,
                        evidence_ids=claim.evidence_ids,
                        fail_below=self.settings.issuer_fail_below,
                        review_through=self.settings.issuer_escalate_through,
                    ),
                    v_iss_002.check(
                        issuer,
                        self.registry,
                        claim_id=claim.claim_id,
                        evidence_ids=claim.evidence_ids,
                        review_min=self.settings.issuer_fail_below,
                        review_max=self.settings.issuer_escalate_through,
                    ),
                ]
            )

            certificate_doc = context.certificate_doc_by_claim.get(
                claim.claim_id, claim.doc_id
            )
            bom_doc = context.bom_doc_by_claim.get(claim.claim_id)
            certificate_materials = _as_strings(
                fields.get("scope_materials", materials_by_doc.get(certificate_doc))
            )
            bom_materials = materials_by_doc.get(bom_doc) if bom_doc is not None else None
            results.append(
                v_scope_001.check(
                    certificate_materials,
                    bom_materials,
                    claim_id=claim.claim_id,
                    evidence_ids=claim.evidence_ids,
                )
            )
            results.append(
                v_scope_002.check(
                    context.facility_ids_by_doc.get(certificate_doc),
                    context.facility_ids_by_doc.get(bom_doc) if bom_doc else None,
                    claim_id=claim.claim_id,
                    evidence_ids=claim.evidence_ids,
                    cert_facility_name=context.facility_names_by_doc.get(certificate_doc),
                    bom_facility_name=context.facility_names_by_doc.get(bom_doc)
                    if bom_doc
                    else None,
                )
            )
            results.extend(
                [
                    v_xdoc_001.check(
                        list(supplier_ids.values()),
                        claim_id=claim.claim_id,
                        evidence_ids=claim.evidence_ids,
                    ),
                    v_xdoc_002.check(
                        materials_by_doc,
                        claim_id=claim.claim_id,
                        evidence_ids=claim.evidence_ids,
                    ),
                    v_conf_001.check(
                        claim.extractor_confidence,
                        context.risk_score,
                        self.settings.confidence_base,
                        self.settings.confidence_moderate_risk,
                        self.settings.confidence_high_risk,
                        self.settings.risk_moderate_threshold,
                        self.settings.risk_high_threshold,
                        claim_id=claim.claim_id,
                        evidence_ids=claim.evidence_ids,
                    ),
                ]
            )

            page_claims = context.page_claims_by_doc.get(claim.doc_id)
            if page_claims is not None:
                results.append(
                    v_page_001.check(
                        page_claims,
                        context.page_counts_by_doc.get(claim.doc_id),
                        claim_id=claim.claim_id,
                        evidence_ids=claim.evidence_ids,
                    )
                )
            external_lookup = context.external_lookups_by_claim.get(claim.claim_id)
            if external_lookup is not None:
                results.extend(
                    [
                        v_ext_001.check(
                            external_lookup,
                            claim_id=claim.claim_id,
                            evidence_ids=claim.evidence_ids,
                        ),
                        v_ext_002.check(
                            external_lookup,
                            context.assessment_date,
                            self.settings.snapshot_max_age_days,
                            claim_id=claim.claim_id,
                            evidence_ids=claim.evidence_ids,
                        ),
                        v_ext_003.check(
                            external_lookup,
                            claim_id=claim.claim_id,
                            evidence_ids=claim.evidence_ids,
                            confirmed_match_threshold=self.settings.external_confirmed_match,
                        ),
                        v_ext_900.check(
                            external_lookup,
                            claim_id=claim.claim_id,
                            evidence_ids=claim.evidence_ids,
                        ),
                    ]
                )
            if claim.claim_id in context.sanctions_matches_by_claim:
                matches = context.sanctions_matches_by_claim[claim.claim_id]
                results.extend(
                    [
                        v_sanc_001.check(
                            matches,
                            claim_id=claim.claim_id,
                            evidence_ids=claim.evidence_ids,
                        ),
                        v_sanc_002.check(
                            matches,
                            claim_id=claim.claim_id,
                            evidence_ids=claim.evidence_ids,
                            review_threshold=self.settings.sanctions_fuzzy_review,
                        ),
                    ]
                )
        return results

    def escalation_state(
        self,
        verdicts: Sequence[Verdict],
        risk_score: float,
        critical_risk_threshold: float | None = None,
    ) -> EscalationState:
        """Derive escalation and its priority without changing rule outcomes."""
        critical_threshold = (
            self.settings.risk_high_threshold
            if critical_risk_threshold is None
            else critical_risk_threshold
        )
        if not 0.0 <= risk_score <= 1.0 or not 0.0 <= critical_threshold <= 1.0:
            raise ValueError("risk values must be between 0 and 1")
        triggered = [
            verdict
            for verdict in verdicts
            if verdict.outcome == "escalate"
        ]
        critical = risk_score >= critical_threshold or any(
            verdict.details.get("priority") == "critical" for verdict in verdicts
        )
        first = triggered[0] if triggered else None
        return EscalationState(
            is_escalated=bool(triggered) or critical,
            priority="critical" if critical else "normal",
            reason=first.reason_code if first is not None else "",
            triggered_by_rule=first.rule_id if first is not None else None,
            details={
                "triggered_rule_ids": [verdict.rule_id for verdict in triggered],
                "risk_score": risk_score,
                "critical_risk_threshold": critical_threshold,
            },
        )
