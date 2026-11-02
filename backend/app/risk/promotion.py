"""Validation-only model promotion logic."""

from collections.abc import Mapping


def select_promoted_model(
    validation_metrics: Mapping[str, Mapping[str, float]],
    *,
    auroc_margin: float,
    brier_margin: float,
) -> tuple[str, dict[str, bool]]:
    """Promote the LSTM only when it clears both baselines on both metrics."""
    if auroc_margin < 0 or brier_margin < 0:
        raise ValueError("promotion margins must be non-negative")
    required = {"logreg", "xgboost", "lstm"}
    if set(validation_metrics) != required:
        raise ValueError("validation metrics must contain logreg, xgboost, and lstm")
    for name, metrics in validation_metrics.items():
        if not {"auroc", "brier_score"}.issubset(metrics):
            raise ValueError(f"{name} validation metrics are incomplete")
    lstm = validation_metrics["lstm"]
    comparisons: dict[str, bool] = {}
    for baseline_name in ("logreg", "xgboost"):
        baseline = validation_metrics[baseline_name]
        comparisons[baseline_name] = (
            lstm["auroc"] >= baseline["auroc"] + auroc_margin
            and lstm["brier_score"] <= baseline["brier_score"] - brier_margin
        )
    if all(comparisons.values()):
        return "lstm", comparisons
    baseline_name = max(
        ("logreg", "xgboost"),
        key=lambda name: (
            validation_metrics[name]["auroc"],
            -validation_metrics[name]["brier_score"],
            name,
        ),
    )
    return baseline_name, comparisons
