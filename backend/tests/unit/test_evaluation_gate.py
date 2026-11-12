"""Regression coverage for the aggregate evaluation gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_evaluations import evaluate_reports


def _write_report(directory: Path, name: str, report: dict[str, object]) -> None:
    (directory / f"{name}.json").write_text(json.dumps(report), encoding="utf-8")


def _valid_reports(directory: Path) -> dict[str, dict[str, object]]:
    reports: dict[str, dict[str, object]] = {
        "extraction": {
            "model_architecture": "LayoutLMv3 token classification (fine-tuned)",
            "macro_f1": 0.99,
            "overall_mean_bbox_iou": 0.31,
            "is_gate_passed": True,
        },
        "redaction": {"total_leaked": 0, "overall_leakage_rate": 0.0},
        "rag": {
            "citation_metrics": {
                "citation_precision_at_k": 0.2,
                "citation_recall_at_k": 1.0,
            },
            "date_filter_violations": {"total": 0, "per_mode": {"hybrid": 0}},
            "gates": {
                "citation_precision_at_5": True,
                "citation_recall_at_5": True,
                "date_filter_violations": True,
                "golden_query_count": True,
                "no_support_accuracy": True,
                "no_support_query_count": True,
                "supported_query_recall": True,
            },
            "status": "offline_pass_ragas_not_run",
        },
        "risk": {
            "models": {"xgboost": {"test": {"auroc": 0.99, "brier_score": 0.005}}}
        },
        "router": {
            "metrics": {"logreg": {"validation": {"macro_f1": 0.95}}},
            "decision": {"selected_model": "logreg"},
            "latency": {"logreg": {"p95_ms": 10.0}},
        },
    }
    for name, report in reports.items():
        _write_report(directory, name, report)
    return reports


def test_evaluation_gate_accepts_metrics_at_thresholds(tmp_path: Path) -> None:
    _valid_reports(tmp_path)
    verifier: dict[str, object] = {
        "expected_verdict_accuracy": 1.0,
        "escalation_accuracy": 1.0,
    }

    checks = evaluate_reports(tmp_path, verifier)

    assert checks
    assert all(check.passed for check in checks)


def test_evaluation_gate_fails_closed_when_a_metric_regresses(tmp_path: Path) -> None:
    reports = _valid_reports(tmp_path)
    reports["redaction"]["total_leaked"] = 1
    _write_report(tmp_path, "redaction", reports["redaction"])

    checks = evaluate_reports(
        tmp_path,
        {"expected_verdict_accuracy": 1.0, "escalation_accuracy": 1.0},
    )

    assert not next(check for check in checks if check.name == "Privacy leaked seeds").passed


def test_evaluation_gate_rejects_heuristic_metrics_as_layoutlm_results(
    tmp_path: Path,
) -> None:
    reports = _valid_reports(tmp_path)
    reports["extraction"]["model_architecture"] = "Heuristic Layout Extractor"
    _write_report(tmp_path, "extraction", reports["extraction"])

    checks = evaluate_reports(
        tmp_path,
        {"expected_verdict_accuracy": 1.0, "escalation_accuracy": 1.0},
    )

    assert not next(
        check for check in checks if check.name == "Extraction model provenance"
    ).passed
    assert not next(
        check for check in checks if check.name == "Extraction macro F1"
    ).passed
    assert not next(
        check for check in checks if check.name == "Extraction bbox IoU"
    ).passed


def test_evaluation_gate_rejects_missing_reports(tmp_path: Path) -> None:
    _valid_reports(tmp_path)
    (tmp_path / "risk.json").unlink()

    with pytest.raises(FileNotFoundError, match="risk.json"):
        evaluate_reports(
            tmp_path,
            {"expected_verdict_accuracy": 1.0, "escalation_accuracy": 1.0},
        )
