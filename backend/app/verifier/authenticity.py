"""Phase 4B: Document Authenticity, Digital Signature & Forensic Forgery Detection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal
from pydantic import BaseModel, Field

AuthenticityLevel = Literal[
    "INDEPENDENTLY_VERIFIED",
    "CONSISTENT_NOT_VERIFIED",
    "SUSPECTED_TAMPERING",
    "UNVERIFIABLE",
]


class ForensicSignal(BaseModel):
    """Forensic flag raised during low-level document analysis."""
    signal_id: str
    severity: Literal["low", "medium", "high", "critical"]
    description: str
    page: int = 1
    bbox: list[int] | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AuthenticityReport(BaseModel):
    """Comprehensive evaluation of document authenticity and provenance outside the PDF."""
    level: AuthenticityLevel
    can_auto_approve: bool
    tamper_risk: Literal["LOW", "MEDIUM", "HIGH"]
    signals: list[ForensicSignal] = Field(default_factory=list)
    digital_signature_status: Literal["SIGNATURE_VALID", "SIGNATURE_INVALID", "MODIFIED_AFTER_SIGNING", "UNSIGNED"] = "UNSIGNED"
    registry_verified: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class DocumentAuthenticityEngine:
    """Evaluates external registry existence, PDF forensics, and digital signatures."""

    @classmethod
    def evaluate(
        cls,
        extracted_cert_number: str | None,
        issuer: str | None,
        metadata: dict[str, Any] | None = None,
        is_known_registry_match: bool = False,
        has_digital_signature: bool = False,
        signature_valid: bool = False,
        forensic_anomalies: list[str] | None = None,
    ) -> AuthenticityReport:
        signals: list[ForensicSignal] = []

        # 1. Digital Signature Check
        sig_status = "UNSIGNED"
        if has_digital_signature:
            sig_status = "SIGNATURE_VALID" if signature_valid else "SIGNATURE_INVALID"
            if not signature_valid:
                signals.append(
                    ForensicSignal(
                        signal_id="FOR-SIG-001",
                        severity="critical",
                        description="PDF digital signature is invalid or document was modified after signing",
                    )
                )

        # 2. Tamper Heuristics / Forensic signals
        if forensic_anomalies:
            for anomaly in forensic_anomalies:
                signals.append(
                    ForensicSignal(
                        signal_id="FOR-MET-001",
                        severity="high",
                        description=f"Forensic irregularity detected: {anomaly}",
                    )
                )

        # 3. Scheme Registry Check
        # If external registry explicitly confirmed the certificate number outside the document
        if is_known_registry_match and sig_status != "SIGNATURE_INVALID":
            return AuthenticityReport(
                level="INDEPENDENTLY_VERIFIED",
                can_auto_approve=len(signals) == 0,
                tamper_risk="LOW",
                signals=signals,
                digital_signature_status=sig_status,
                registry_verified=True,
                details={"rationale": "Certificate number verified in authoritative scheme database"},
            )

        # 4. Suspected tampering if critical/high forensic signals exist
        if any(s.severity in ("critical", "high") for s in signals):
            return AuthenticityReport(
                level="SUSPECTED_TAMPERING",
                can_auto_approve=False,
                tamper_risk="HIGH",
                signals=signals,
                digital_signature_status=sig_status,
                registry_verified=False,
                details={"rationale": "Forensic inconsistencies or broken signature detected"},
            )

        # 5. Internally consistent but unverified outside PDF
        if extracted_cert_number and issuer:
            return AuthenticityReport(
                level="CONSISTENT_NOT_VERIFIED",
                can_auto_approve=False,  # Never auto-approve unverified documents
                tamper_risk="MEDIUM",
                signals=signals,
                digital_signature_status=sig_status,
                registry_verified=False,
                details={"rationale": "Internal rules pass, but certificate number not confirmed by external scheme registry"},
            )

        # 6. Unverifiable
        return AuthenticityReport(
            level="UNVERIFIABLE",
            can_auto_approve=False,
            tamper_risk="HIGH",
            signals=signals,
            digital_signature_status=sig_status,
            registry_verified=False,
            details={"rationale": "Insufficient identifying data to attempt external verification"},
        )
