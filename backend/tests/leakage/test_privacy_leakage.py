"""Leakage test suite asserting 100% boundary isolation on synthetic PII seeds."""

import json
import re
from pathlib import Path

from backend.app.privacy.outbound_guard import OutboundGuard
from backend.app.privacy.redactor import DocumentRedactor
from backend.app.privacy.vault import TokenVault

REPORTS_DIR = Path("reports")
REDACTION_REPORT = REPORTS_DIR / "redaction.json"
ANNOTATIONS_PATH = Path("data/synthetic/documents_v2/annotations.json")


def test_no_direct_llm_imports_outside_llm_module() -> None:
    """Security audit test: Enforces that no cloud LLM SDKs are imported outside backend/app/llm/."""
    backend_root = Path("backend/app")
    forbidden_imports = [
        re.compile(r"^\s*(?:import\s+google\.genai|from\s+google\.genai\b)"),
        re.compile(r"^\s*(?:import\s+google\.generativeai|from\s+google\.generativeai\b)"),
        re.compile(r"^\s*(?:import\s+openai|from\s+openai\b)"),
    ]

    violations: list[str] = []

    for py_file in backend_root.rglob("*.py"):
        # Allow only inside backend/app/llm/
        if "llm" in py_file.parts:
            continue

        with open(py_file, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                for pat in forbidden_imports:
                    if pat.search(line):
                        violations.append(f"{py_file}:{line_no}: {line.strip()}")

    assert not violations, (
        "Direct LLM provider imports found outside backend/app/llm/:\n" + "\n".join(violations)
    )


def test_no_direct_network_calls_outside_integrations_and_llm() -> None:
    """Security audit test: Enforces that httpx/requests are only imported inside integrations/ and llm/ (R2)."""
    backend_root = Path("backend/app")
    network_imports = [
        re.compile(r"^\s*(?:import\s+httpx|from\s+httpx\b)"),
        re.compile(r"^\s*(?:import\s+requests|from\s+requests\b)"),
        re.compile(r"^\s*(?:import\s+urllib\.request|from\s+urllib\s+import\s+request\b)"),
    ]

    violations: list[str] = []

    for py_file in backend_root.rglob("*.py"):
        # Network clients are confined to the guarded integrations and LLM adapters.
        parts = py_file.parts
        if "integrations" in parts or "llm" in parts:
            continue

        with open(py_file, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                for pat in network_imports:
                    if pat.search(line):
                        violations.append(f"{py_file}:{line_no}: {line.strip()}")

    assert not violations, (
        "Direct network library imports found outside integrations/ and llm/:\n" + "\n".join(violations)
    )


def test_zero_leakage_across_all_privacy_seeds() -> None:
    """Processes all annotated documents and asserts zero seeded PII escapes through OutboundGuard."""
    assert ANNOTATIONS_PATH.exists(), "Annotations file missing. Run make data first."

    with open(ANNOTATIONS_PATH, encoding="utf-8") as f:
        doc_annotations = json.load(f)

    redactor = DocumentRedactor()
    vault = TokenVault(master_key="leakage-test-master-key")
    guard = OutboundGuard(vault=vault)
    tenant_id = "leakage_eval_tenant"

    entity_counts: dict[str, int] = {}
    entity_detected: dict[str, int] = {}
    total_leaked = 0

    # Test across all 180 documents
    for doc_info in doc_annotations:
        pdf_path = Path("data/synthetic/documents_v2") / doc_info["filename"]
        if not pdf_path.exists():
            continue

        # Run document redaction
        redacted_pages = redactor.redact_document(
            file_path=pdf_path,
            tenant_id=tenant_id,
            doc_id=doc_info["doc_id"],
            vault=vault,
        )

        full_redacted_text = "\n".join(p.redacted_text for p in redacted_pages)

        # Check each seeded PII in this document
        for seed in doc_info.get("privacy_seeds", []):
            etype = seed["type"]
            sval = seed["value"].strip()

            entity_counts[etype] = entity_counts.get(etype, 0) + 1

            # Seed should NOT appear in the redacted text
            if sval.lower() in full_redacted_text.lower():
                total_leaked += 1
            else:
                entity_detected[etype] = entity_detected.get(etype, 0) + 1

        # Simulate cloud LLM outbound transmission through OutboundGuard
        # If any vault-known value is present, OutboundGuard must raise PrivacyViolationError
        payload = f"Prompt for LLM summarization:\n{full_redacted_text}"
        payload_hash = guard.verify_and_log_payload(payload, tenant_id=tenant_id)
        assert len(payload_hash) == 64

    # Calculate recall per entity type
    recall_by_entity: dict[str, float] = {}
    for etype, total in entity_counts.items():
        detected = entity_detected.get(etype, 0)
        recall_by_entity[etype] = round(detected / total, 4) if total > 0 else 1.0

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_data = {
        "evaluation_name": "Privacy Boundary Leakage & Redaction Recall",
        "total_documents_tested": len(doc_annotations),
        "total_seeds_tested": sum(entity_counts.values()),
        "total_leaked": total_leaked,
        "overall_leakage_rate": round(total_leaked / sum(entity_counts.values()), 6),
        "recall_per_entity_type": recall_by_entity,
        "entity_counts": entity_counts,
        "is_gate_passed": total_leaked == 0,
    }

    with open(REDACTION_REPORT, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    # Hard gate: ZERO LEAKAGE TOLERANCE
    assert total_leaked == 0, (
        f"Privacy leakage test failed! {total_leaked} seeded PII items leaked into outbound payload."
    )
    for etype, rec in recall_by_entity.items():
        assert rec >= 0.95, f"Redaction recall for {etype} is below threshold: {rec:.2%}"
