"""Evaluate deterministic verifier outcomes against the seeded golden set."""

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.domain.models import Claim, VerificationContext  # noqa: E402
from backend.app.verifier.engine import Verifier  # noqa: E402
from backend.app.verifier.registry_loader import load_approved_issuers  # noqa: E402

DEFAULT_DATASET = ROOT / "data" / "golden" / "golden_set.json"
DEFAULT_OUTPUT = ROOT / "reports" / "verifier.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _case_inputs(case: dict[str, Any]) -> tuple[Claim, VerificationContext]:
    certificate = next(
        document for document in case["documents"] if document["doc_type"] == "certificate"
    )
    bom = next(document for document in case["documents"] if document["doc_type"] == "bom")
    certificate_fields = certificate["fields"]
    bom_fields = bom["fields"]
    claim_id = case["case_id"]
    evidence_id = f"EVIDENCE-{claim_id}"
    claim = Claim(
        claim_id=claim_id,
        claim_text=case["description"],
        doc_id=certificate["doc_id"],
        doc_hash=certificate["doc_hash"],
        page=1,
        extractor_confidence=0.99,
        evidence_ids=[evidence_id],
    )
    context = VerificationContext(
        assessment_date=date.fromisoformat(case["assessment_date"]),
        fields_by_claim={
            claim_id: {
                "issuer": certificate_fields.get("issuer"),
                "valid_from": certificate_fields.get("valid_from"),
                "valid_to": certificate_fields.get("valid_to"),
                "scope_materials": certificate_fields.get("scope_materials"),
            }
        },
        page_claims_by_doc={
            certificate["doc_id"]: [certificate_fields.get("page_claims", "")]
        },
        page_counts_by_doc={
            certificate["doc_id"]: certificate.get("page_count", certificate.get("1", 0))
        },
        materials_by_doc={
            certificate["doc_id"]: [certificate_fields["scope_materials"]],
            bom["doc_id"]: bom_fields.get("materials", []),
        },
        supplier_ids_by_doc={
            certificate["doc_id"]: certificate_fields["supplier_id"],
            bom["doc_id"]: bom_fields["supplier_id"],
        },
        facility_ids_by_doc={
            certificate["doc_id"]: certificate_fields["facility_id"],
            bom["doc_id"]: bom_fields["facility_id"],
        },
        certificate_doc_by_claim={claim_id: certificate["doc_id"]},
        bom_doc_by_claim={claim_id: bom["doc_id"]},
    )
    return claim, context


def evaluate_golden_set(
    dataset_path: Path = DEFAULT_DATASET,
    output_path: Path = DEFAULT_OUTPUT,
    *,
    source_git_sha: str | None = None,
) -> dict[str, Any]:
    """Run all golden cases and write a reproducible, provenance-bearing report."""
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    verifier = Verifier(registry=load_approved_issuers())
    outcome_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"correct": 0, "total": 0}
    )
    escalation_correct = 0
    case_results: list[dict[str, Any]] = []
    for case in dataset["cases"]:
        claim, context = _case_inputs(case)
        verdicts = verifier.verify([claim], context)
        expected = case["expected_verdicts"]
        actual_by_rule = {verdict.rule_id: verdict for verdict in verdicts}
        matched_rules = 0
        for expected_verdict in expected:
            rule_id = expected_verdict["rule_id"]
            actual = actual_by_rule.get(rule_id)
            correct = actual is not None and actual.outcome == expected_verdict["expected_outcome"]
            outcome_counts[rule_id]["total"] += 1
            outcome_counts[rule_id]["correct"] += int(correct)
            matched_rules += int(correct)
        escalation = verifier.escalation_state(verdicts, context.risk_score)
        expected_escalation = case["expected_escalation"]
        escalation_match = escalation.is_escalated == expected_escalation
        escalation_correct += int(escalation_match)
        case_results.append(
            {
                "case_id": case["case_id"],
                "scenario": case["scenario"],
                "expected_verdicts": expected,
                "matched_expected_rules": matched_rules,
                "escalated": escalation.is_escalated,
                "expected_escalation": expected_escalation,
                "escalation_match": escalation_match,
            }
        )

    expected_total = sum(counts["total"] for counts in outcome_counts.values())
    expected_correct = sum(counts["correct"] for counts in outcome_counts.values())
    report: dict[str, Any] = {
        "report_version": "1.0.0",
        "evaluation": "synthetic_golden_set",
        "seed": dataset["seed"],
        "dataset_path": dataset_path.relative_to(ROOT).as_posix(),
        "dataset_sha256": _sha256(dataset_path),
        "source_git_sha": source_git_sha or _git_sha(),
        "case_count": len(case_results),
        "expected_verdict_accuracy": (
            expected_correct / expected_total if expected_total else 0.0
        ),
        "expected_verdicts_correct": expected_correct,
        "expected_verdicts_total": expected_total,
        "escalation_accuracy": (
            escalation_correct / len(case_results) if case_results else 0.0
        ),
        "escalation_cases_correct": escalation_correct,
        "escalation_cases_total": len(case_results),
        "per_rule": {
            rule_id: {
                **counts,
                "accuracy": counts["correct"] / counts["total"],
            }
            for rule_id, counts in sorted(outcome_counts.items())
        },
        "cases": case_results,
        "limitations": [
            "All cases and issuer-registry entries are synthetic/mock.",
            "The golden set does not include V-EXT or V-SANC expected labels.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = evaluate_golden_set(args.dataset, args.output)
    print(
        "Verifier golden set: "
        f"{report['expected_verdicts_correct']}/{report['expected_verdicts_total']} verdicts; "
        f"escalation accuracy {report['escalation_accuracy']:.3f}; "
        f"wrote {args.output}"
    )


if __name__ == "__main__":
    main()
