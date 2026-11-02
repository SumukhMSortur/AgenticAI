"""Versioned inference from locally trained, hash-verified risk artifacts."""

import hashlib
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, cast

import joblib
import numpy as np
import torch
from numpy.typing import NDArray
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

from backend.app.domain.models import RiskForecast
from backend.app.risk.features import (
    apply_standardizer,
    engineered_features,
    sequence_features,
)
from backend.app.risk.lstm import RiskLSTM


class RiskInference:
    """Predict six-month audit risk from a versioned local inference artifact."""

    def __init__(self, artifact: Mapping[str, Any]) -> None:
        # Model-specific estimator objects are loaded only from the hash-verified local bundle.
        self._artifact = dict(artifact)
        if self._artifact.get("artifact_version") != "1.0.0":
            raise ValueError("unsupported risk artifact version")
        if self._artifact.get("model_tag") not in {"logreg", "xgboost", "lstm"}:
            raise ValueError("risk artifact contains an unsupported model tag")

    @classmethod
    def load(cls, path: Path, expected_sha256: str) -> "RiskInference":
        """Verify artifact bytes before loading the trusted local joblib bundle."""
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_sha256:
            raise ValueError("risk artifact SHA-256 does not match the expected value")
        artifact = joblib.load(path)
        if not isinstance(artifact, dict):
            raise ValueError("risk artifact must contain a model bundle")
        return cls(cast(dict[str, Any], artifact))

    def predict(
        self,
        factory_id: str,
        history: Sequence[Mapping[str, object]],
    ) -> RiskForecast:
        """Return a calibrated forecast with model and baseline provenance."""
        window = int(self._artifact["feature_window_months"])
        sequence = sequence_features(history, window)
        model_tag = cast(str, self._artifact["model_tag"])
        if model_tag == "lstm":
            score = self._lstm_score(sequence)
        else:
            score = self._baseline_score(sequence, model_tag)
        calibrator = cast(LogisticRegression, self._artifact["calibrator"])
        probability = float(
            calibrator.predict_proba(np.asarray([[score]], dtype=np.float64))[0, 1]
        )
        if not math.isfinite(probability):
            raise ValueError("risk model produced a non-finite probability")
        return RiskForecast(
            factory_id=factory_id,
            p_fail_6m=min(1.0, max(0.0, probability)),
            model_tag=cast(Literal["logreg", "xgboost", "lstm"], model_tag),
            baseline_comparison=cast(dict[str, Any], self._artifact["baseline_comparison"]),
        )

    def _baseline_score(
        self, sequence: NDArray[np.float64], model_tag: str
    ) -> float:
        features = engineered_features(sequence).reshape(1, -1)
        normalized = apply_standardizer(
            features,
            np.asarray(self._artifact["engineered_mean"], dtype=np.float64),
            np.asarray(self._artifact["engineered_scale"], dtype=np.float64),
        )
        if model_tag == "logreg":
            estimator = cast(LogisticRegression, self._artifact["estimator"])
            return float(estimator.decision_function(normalized)[0])
        estimator = cast(XGBClassifier, self._artifact["estimator"])
        probability = float(estimator.predict_proba(normalized)[0, 1])
        return _probability_logit(probability)

    def _lstm_score(self, sequence: NDArray[np.float64]) -> float:
        normalized = apply_standardizer(
            sequence,
            np.asarray(self._artifact["sequence_mean"], dtype=np.float64),
            np.asarray(self._artifact["sequence_scale"], dtype=np.float64),
        )
        network = RiskLSTM(
            feature_count=int(self._artifact["feature_count"]),
            hidden_size=int(self._artifact["lstm_hidden_size"]),
        )
        network.load_state_dict(cast(dict[str, Any], self._artifact["state_dict"]))
        network.eval()
        with torch.no_grad():
            tensor = torch.as_tensor(normalized, dtype=torch.float32).unsqueeze(0)
            return float(network(tensor).item())


def _probability_logit(probability: float) -> float:
    """Convert a clipped probability to a finite calibration score."""
    bounded = min(1.0 - 1e-7, max(1e-7, probability))
    return math.log(bounded / (1.0 - bounded))
