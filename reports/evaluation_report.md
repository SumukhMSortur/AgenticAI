# Evaluation Report

**Overall:** PASS
**Source revision:** unavailable (working tree has no Git metadata)
**Scope:** Current verifier golden-set execution plus the checked-in extraction, privacy, RAG, risk, and router evaluation reports.
**Limitations:** Metrics from prior model evaluations are read from their versioned JSON reports, not retrained here. Ragas faithfulness and answer relevance remain `not_run` unless separately enabled.

| Gate | Metric | Value | Threshold | Result |
|---|---|---:|---|---|
| Extraction model provenance | `model_architecture` | LayoutLMv3 token classification (fine-tuned) | LayoutLMv3 token classification (fine-tuned) | PASS |
| Extraction macro F1 | `macro_f1` | 1 | >= 0.95 | PASS |
| Extraction bbox IoU | `overall_mean_bbox_iou` | 1 | >= 0.30 | PASS |
| Extraction report gate | `is_gate_passed` | true | true | PASS |
| Privacy leaked seeds | `total_leaked` | 0 | == 0 | PASS |
| Privacy leakage rate | `overall_leakage_rate` | 0 | == 0 | PASS |
| RAG citation precision@5 | `citation_metrics.citation_precision_at_k` | 0.2 | >= 0.20 | PASS |
| RAG citation recall@5 | `citation_metrics.citation_recall_at_k` | 1 | >= 1.00 | PASS |
| RAG date-filter violations | `date_filter_violations.total` | 0 | == 0 | PASS |
| RAG offline gate | `status` | offline_pass_ragas_not_run | offline_pass_ragas_not_run (Ragas is explicitly optional) | PASS |
| Risk XGBoost test AUROC | `models.xgboost.test.auroc` | 1 | >= 0.95 | PASS |
| Risk XGBoost test Brier score | `models.xgboost.test.brier_score` | 0.00022914 | <= 0.01 | PASS |
| Router selected-model validation macro F1 | `metrics.logreg.validation.macro_f1` | 0.96633 | >= 0.90 | PASS |
| Router p95 latency | `latency.logreg.p95_ms` | 13.4008 | <= 50 ms | PASS |
| Verifier expected-verdict accuracy | `expected_verdict_accuracy` | 1 | >= 0.99 | PASS |
| Verifier escalation accuracy | `escalation_accuracy` | 1 | >= 0.99 | PASS |
| RAG reported citation_precision_at_5 | `gates.citation_precision_at_5` | true | true | PASS |
| RAG reported citation_recall_at_5 | `gates.citation_recall_at_5` | true | true | PASS |
| RAG reported date_filter_violations | `gates.date_filter_violations` | true | true | PASS |
| RAG reported golden_query_count | `gates.golden_query_count` | true | true | PASS |
| RAG reported no_support_accuracy | `gates.no_support_accuracy` | true | true | PASS |
| RAG reported no_support_query_count | `gates.no_support_query_count` | true | true | PASS |
| RAG reported supported_query_recall | `gates.supported_query_recall` | true | true | PASS |
