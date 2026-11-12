"""Aggregate the recorded model gates and rerun the deterministic verifier golden set."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.evaluate_verifier import evaluate_golden_set

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DEFAULT_OUTPUT = REPORTS / "evaluation_report.md"
GIT_UNAVAILABLE = "unavailable (working tree has no Git metadata)"


@dataclass(frozen=True)
class Gate:
    name: str
    metric: str
    actual: float | str
    requirement: str
    passed: bool


def _read_report(reports_dir: Path, name: str) -> dict[str, Any]:
    path = reports_dir / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Required evaluation report is missing: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError(f"Evaluation report must contain a JSON object: {path}")
    return report


def _number(report: dict[str, Any], *path: str) -> float:
    value: Any = report
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"Missing evaluation metric: {'.'.join(path)}")
        value = value[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Evaluation metric must be numeric: {'.'.join(path)}")
    if not math.isfinite(float(value)):
        raise ValueError(f"Evaluation metric must be finite: {'.'.join(path)}")
    return float(value)


def _boolean(report: dict[str, Any], *path: str) -> bool:
    value: Any = report
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"Missing evaluation gate: {'.'.join(path)}")
        value = value[key]
    if not isinstance(value, bool):
        raise ValueError(f"Evaluation gate must be boolean: {'.'.join(path)}")
    return value


def _gate(
    name: str,
    metric: str,
    actual: float | str,
    requirement: str,
    passed: bool,
) -> Gate:
    rendered = f"{actual:g}" if isinstance(actual, float) else actual
    return Gate(name, metric, rendered, requirement, passed)


def evaluate_reports(reports_dir: Path, verifier: dict[str, Any]) -> list[Gate]:
    extraction = _read_report(reports_dir, "extraction")
    extraction_model = extraction.get("model_architecture")
    is_fine_tuned_layoutlm = (
        extraction_model == "LayoutLMv3 token classification (fine-tuned)"
    )
    privacy = _read_report(reports_dir, "redaction")
    rag = _read_report(reports_dir, "rag")
    risk = _read_report(reports_dir, "risk")
    router = _read_report(reports_dir, "router")
    date_filter_total = _number(rag, "date_filter_violations", "total")
    per_mode_violations = rag["date_filter_violations"].get("per_mode")
    if not isinstance(per_mode_violations, dict) or not all(
        isinstance(violations, int) and not isinstance(violations, bool)
        for violations in per_mode_violations.values()
    ):
        raise ValueError("RAG per-mode date-filter violations must be integer counts.")
    all_date_filters_clean = date_filter_total == 0 and all(
        violations == 0 for violations in per_mode_violations.values()
    )

    checks = [
        _gate(
            "Extraction model provenance",
            "model_architecture",
            str(extraction_model or "missing"),
            "LayoutLMv3 token classification (fine-tuned)",
            is_fine_tuned_layoutlm,
        ),
        _gate(
            "Extraction macro F1",
            "macro_f1",
            _number(extraction, "macro_f1"),
            ">= 0.95",
            is_fine_tuned_layoutlm and _number(extraction, "macro_f1") >= 0.95,
        ),
        _gate(
            "Extraction bbox IoU",
            "overall_mean_bbox_iou",
            _number(extraction, "overall_mean_bbox_iou"),
            ">= 0.30",
            is_fine_tuned_layoutlm
            and _number(extraction, "overall_mean_bbox_iou") >= 0.30,
        ),
        _gate(
            "Extraction report gate",
            "is_gate_passed",
            str(_boolean(extraction, "is_gate_passed")).lower(),
            "true",
            is_fine_tuned_layoutlm and _boolean(extraction, "is_gate_passed"),
        ),
        _gate(
            "Privacy leaked seeds",
            "total_leaked",
            _number(privacy, "total_leaked"),
            "== 0",
            _number(privacy, "total_leaked") == 0,
        ),
        _gate(
            "Privacy leakage rate",
            "overall_leakage_rate",
            _number(privacy, "overall_leakage_rate"),
            "== 0",
            _number(privacy, "overall_leakage_rate") == 0,
        ),
        _gate(
            "RAG citation precision@5",
            "citation_metrics.citation_precision_at_k",
            _number(rag, "citation_metrics", "citation_precision_at_k"),
            ">= 0.20",
            _number(rag, "citation_metrics", "citation_precision_at_k") >= 0.20,
        ),
        _gate(
            "RAG citation recall@5",
            "citation_metrics.citation_recall_at_k",
            _number(rag, "citation_metrics", "citation_recall_at_k"),
            ">= 1.00",
            _number(rag, "citation_metrics", "citation_recall_at_k") >= 1.00,
        ),
        _gate(
            "RAG date-filter violations",
            "date_filter_violations.total",
            date_filter_total,
            "== 0",
            all_date_filters_clean,
        ),
        _gate(
            "RAG offline gate",
            "status",
            str(rag.get("status")),
            "offline_pass_ragas_not_run (Ragas is explicitly optional)",
            rag.get("status") == "offline_pass_ragas_not_run",
        ),
        _gate(
            "Risk XGBoost test AUROC",
            "models.xgboost.test.auroc",
            _number(risk, "models", "xgboost", "test", "auroc"),
            ">= 0.95",
            _number(risk, "models", "xgboost", "test", "auroc") >= 0.95,
        ),
        _gate(
            "Risk XGBoost test Brier score",
            "models.xgboost.test.brier_score",
            _number(risk, "models", "xgboost", "test", "brier_score"),
            "<= 0.01",
            _number(risk, "models", "xgboost", "test", "brier_score") <= 0.01,
        ),
        _gate(
            "Router selected-model validation macro F1",
            "metrics.logreg.validation.macro_f1",
            _number(router, "metrics", "logreg", "validation", "macro_f1"),
            ">= 0.90",
            _number(router, "metrics", "logreg", "validation", "macro_f1") >= 0.90
            and router.get("decision", {}).get("selected_model") == "logreg",
        ),
        _gate(
            "Router p95 latency",
            "latency.logreg.p95_ms",
            _number(router, "latency", "logreg", "p95_ms"),
            "<= 50 ms",
            _number(router, "latency", "logreg", "p95_ms") <= 50,
        ),
        _gate(
            "Verifier expected-verdict accuracy",
            "expected_verdict_accuracy",
            _number(verifier, "expected_verdict_accuracy"),
            ">= 0.99",
            _number(verifier, "expected_verdict_accuracy") >= 0.99,
        ),
        _gate(
            "Verifier escalation accuracy",
            "escalation_accuracy",
            _number(verifier, "escalation_accuracy"),
            ">= 0.99",
            _number(verifier, "escalation_accuracy") >= 0.99,
        ),
    ]
    for gate_name in (
        "citation_precision_at_5",
        "citation_recall_at_5",
        "date_filter_violations",
        "golden_query_count",
        "no_support_accuracy",
        "no_support_query_count",
        "supported_query_recall",
    ):
        gate_passed = _boolean(rag, "gates", gate_name)
        checks.append(
            Gate(
                f"RAG reported {gate_name}",
                f"gates.{gate_name}",
                str(gate_passed).lower(),
                "true",
                gate_passed,
            )
        )
    return checks


def _markdown(checks: list[Gate], git_note: str) -> str:
    status = "PASS" if all(check.passed for check in checks) else "FAIL"
    rows = [
        "# Evaluation Report",
        "",
        f"**Overall:** {status}",
        f"**Source revision:** {git_note}",
        "**Scope:** Current verifier golden-set execution plus the checked-in extraction, privacy, RAG, risk, and router evaluation reports.",
        "**Limitations:** Metrics from prior model evaluations are read from their versioned JSON reports, not retrained here. Ragas faithfulness and answer relevance remain `not_run` unless separately enabled.",
        "",
        "| Gate | Metric | Value | Threshold | Result |",
        "|---|---|---:|---|---|",
    ]
    rows.extend(
        f"| {check.name} | `{check.metric}` | {check.actual} | {check.requirement} | "
        f"{'PASS' if check.passed else 'FAIL'} |"
        for check in checks
    )
    rows.append("")
    return "\n".join(rows)


def run_evaluations(reports_dir: Path = REPORTS, output_path: Path = DEFAULT_OUTPUT) -> bool:
    with tempfile.TemporaryDirectory(prefix="ecochain-eval-") as directory:
        verifier = evaluate_golden_set(
            output_path=Path(directory) / "verifier.json",
            source_git_sha=GIT_UNAVAILABLE,
        )
    checks = evaluate_reports(reports_dir, verifier)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_markdown(checks, GIT_UNAVAILABLE), encoding="utf-8")
    passed = all(check.passed for check in checks)
    print(f"Evaluation gates: {sum(check.passed for check in checks)}/{len(checks)} passed.")
    print(f"Report: {output_path}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    return 0 if run_evaluations(args.reports_dir, args.output) else 1


if __name__ == "__main__":
    raise SystemExit(main())
