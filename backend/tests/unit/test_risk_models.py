"""Tests for leakage-aware risk features, calibration, promotion, and inference."""

import hashlib
from pathlib import Path

import joblib
import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

from backend.app.risk.config import RiskConfig, load_risk_config
from backend.app.risk.features import (
    FEATURE_NAMES,
    apply_standardizer,
    engineered_features,
    fit_standardizer,
    sequence_features,
)
from backend.app.risk.inference import RiskInference
from backend.app.risk.lstm import RiskLSTM
from backend.app.risk.promotion import select_promoted_model
from ml.train_risk import _bootstrap_intervals, _metrics


def _history(months: int = 12) -> list[dict[str, int | float]]:
    return [
        {
            "month": month,
            **{name: float(month + index) for index, name in enumerate(FEATURE_NAMES)},
        }
        for month in range(1, months + 1)
    ]


def _calibrator() -> LogisticRegression:
    model = LogisticRegression(random_state=42)
    model.fit(np.array([[-2.0], [-1.0], [1.0], [2.0]]), np.array([0, 0, 1, 1]))
    return model


def _baseline_artifact() -> dict:
    values = np.vstack([np.zeros(20), np.ones(20), -np.ones(20), np.full(20, 2.0)])
    estimator = LogisticRegression(random_state=42).fit(values, [0, 0, 1, 1])
    return {
        "artifact_version": "1.0.0",
        "model_tag": "logreg",
        "feature_window_months": 12,
        "feature_count": len(FEATURE_NAMES),
        "engineered_mean": np.zeros(20),
        "engineered_scale": np.ones(20),
        "sequence_mean": np.zeros(5),
        "sequence_scale": np.ones(5),
        "estimator": estimator,
        "calibrator": _calibrator(),
        "baseline_comparison": {"logreg": {"auroc": 0.8, "brier_score": 0.2}},
    }


def test_sequence_features_use_only_requested_history_and_validate_values() -> None:
    features = sequence_features(_history(14), 12)
    assert features.shape == (12, 5)
    assert features[0, 0] == 3.0
    assert features[-1, 0] == 14.0

    with pytest.raises(ValueError, match="at least 12 months"):
        sequence_features(_history(11), 12)
    with pytest.raises(ValueError, match="at least 2"):
        sequence_features(_history(), 1)
    out_of_order = _history()
    out_of_order[-1]["month"] = 20
    with pytest.raises(ValueError, match="consecutive"):
        sequence_features(out_of_order, 12)
    invalid_month = _history()
    invalid_month[-1]["month"] = 12.5
    with pytest.raises(ValueError, match="consecutive"):
        sequence_features(invalid_month, 12)
    malformed = _history()
    malformed[-1]["safety_incidents"] = -1
    with pytest.raises(ValueError, match="finite non-negative"):
        sequence_features(malformed, 12)
    malformed[-1]["safety_incidents"] = True
    with pytest.raises(ValueError, match="finite non-negative"):
        sequence_features(malformed, 12)


def test_engineered_features_and_train_only_standardization() -> None:
    sequence = sequence_features(_history(), 12)
    summary = engineered_features(sequence)
    assert summary.shape == (20,)
    assert np.array_equal(summary[:5], sequence[-1])

    training = np.array([[1.0, 4.0], [3.0, 4.0]])
    mean, scale = fit_standardizer(training)
    assert np.array_equal(mean, np.array([2.0, 4.0]))
    assert np.array_equal(scale, np.array([1.0, 1.0]))
    transformed = apply_standardizer(np.array([[100.0, 5.0]]), mean, scale)
    assert np.array_equal(transformed, np.array([[98.0, 1.0]]))
    with pytest.raises(ValueError, match="feature dimensions"):
        apply_standardizer(np.ones((1, 3)), mean, scale)
    with pytest.raises(ValueError, match="shape"):
        engineered_features(np.ones((12, 4)))
    with pytest.raises(ValueError, match="at least one sample"):
        fit_standardizer(np.asarray([]))


def test_config_validation_and_promotion_use_validation_metrics(tmp_path: Path) -> None:
    config = load_risk_config()
    assert config.seed == 42
    with pytest.raises(ValueError):
        RiskConfig.model_validate({**config.model_dump(), "lstm_patience": 0})
    config_path = tmp_path / "invalid-risk.yaml"
    config_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_risk_config(config_path)

    metrics = {
        "logreg": {"auroc": 0.75, "brier_score": 0.18},
        "xgboost": {"auroc": 0.80, "brier_score": 0.16},
        "lstm": {"auroc": 0.82, "brier_score": 0.15},
    }
    chosen, comparison = select_promoted_model(
        metrics, auroc_margin=0.01, brier_margin=0.005
    )
    assert chosen == "lstm"
    assert comparison == {"logreg": True, "xgboost": True}

    metrics["lstm"] = {"auroc": 0.81, "brier_score": 0.16}
    chosen, comparison = select_promoted_model(
        metrics, auroc_margin=0.01, brier_margin=0.005
    )
    assert chosen == "xgboost"
    assert comparison == {"logreg": True, "xgboost": False}
    with pytest.raises(ValueError, match="non-negative"):
        select_promoted_model(metrics, auroc_margin=-0.1, brier_margin=0.0)
    with pytest.raises(ValueError, match="must contain"):
        select_promoted_model({"lstm": {}}, auroc_margin=0.0, brier_margin=0.0)
    with pytest.raises(ValueError, match="incomplete"):
        select_promoted_model(
            {"logreg": {}, "xgboost": {}, "lstm": {}},
            auroc_margin=0.0,
            brier_margin=0.0,
        )


def test_risk_inference_verifies_artifact_hash_and_predicts(tmp_path: Path) -> None:
    artifact_path = tmp_path / "risk.joblib"
    artifact = _baseline_artifact()
    joblib.dump(artifact, artifact_path, compress=3)
    expected_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    inference = RiskInference.load(artifact_path, expected_hash)
    forecast = inference.predict("FACT-1", _history())
    assert forecast.factory_id == "FACT-1"
    assert 0.0 <= forecast.p_fail_6m <= 1.0
    assert forecast.model_tag == "logreg"
    assert forecast.baseline_comparison["logreg"]["auroc"] == 0.8
    with pytest.raises(ValueError, match="SHA-256"):
        RiskInference.load(artifact_path, "not-the-right-hash")


def test_risk_inference_supports_serialized_lstm_weights() -> None:
    model = RiskLSTM(feature_count=5, hidden_size=3)
    artifact = _baseline_artifact()
    artifact.update(
        {
            "model_tag": "lstm",
            "lstm_hidden_size": 3,
            "state_dict": model.state_dict(),
        }
    )
    forecast = RiskInference(artifact).predict("FACT-LSTM", _history())
    assert forecast.model_tag == "lstm"
    assert 0.0 <= forecast.p_fail_6m <= 1.0


def test_risk_inference_xgboost_path_and_artifact_shape_validation(tmp_path: Path) -> None:
    training = np.vstack([np.zeros(20), np.ones(20), -np.ones(20), np.full(20, 2.0)])
    estimator = XGBClassifier(
        n_estimators=2,
        max_depth=2,
        n_jobs=1,
        tree_method="hist",
        random_state=42,
        eval_metric="logloss",
    ).fit(training, [0, 0, 1, 1])
    artifact = _baseline_artifact()
    artifact.update({"model_tag": "xgboost", "estimator": estimator})
    forecast = RiskInference(artifact).predict("FACT-XGB", _history())
    assert forecast.model_tag == "xgboost"
    assert 0.0 <= forecast.p_fail_6m <= 1.0

    with pytest.raises(ValueError, match="version"):
        RiskInference({**artifact, "artifact_version": "2.0.0"})
    with pytest.raises(ValueError, match="model tag"):
        RiskInference({**artifact, "model_tag": "unknown"})
    artifact_path = tmp_path / "not-a-bundle.joblib"
    joblib.dump([], artifact_path)
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="model bundle"):
        RiskInference.load(artifact_path, digest)

    class NonFiniteCalibrator:
        def predict_proba(self, _scores: np.ndarray) -> np.ndarray:
            return np.array([[0.5, np.nan]])

    non_finite = _baseline_artifact()
    non_finite["calibrator"] = NonFiniteCalibrator()
    with pytest.raises(ValueError, match="non-finite"):
        RiskInference(non_finite).predict("FACT-NAN", _history())


def test_test_metrics_and_bootstrap_are_deterministic() -> None:
    labels = np.array([0, 1, 0, 1, 1, 0, 1, 0])
    probabilities = np.array([0.1, 0.8, 0.3, 0.75, 0.6, 0.2, 0.9, 0.4])
    metrics = _metrics(probabilities, labels, 4)
    assert set(metrics) == {"auroc", "pr_auc", "brier_score", "ece", "reliability_curve"}
    first = _bootstrap_intervals(probabilities, labels, 4, 40, 42)
    second = _bootstrap_intervals(probabilities, labels, 4, 40, 42)
    assert first == second
