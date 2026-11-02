"""Local embedding-based intent router and verified artifact loader."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import joblib
import numpy as np
from numpy.typing import NDArray

from backend.app.router.config import load_router_config
from backend.app.router.embedding import load_text_encoder
from backend.app.router.evaluation import predict_labels

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_REPORT_PATH = _PROJECT_ROOT / "reports" / "router.json"
_ARTIFACT_ROOT = _PROJECT_ROOT / "artifacts" / "router"


class TextEncoder(Protocol):
    """Sentence embedding provider interface used by intent routing."""

    def encode(
        self,
        sentences: list[str],
        *,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> NDArray[np.float32]: ...


class ProbabilityClassifier(Protocol):
    """Classifier interface shared by the Logistic Regression and Keras models."""

    def predict_proba(self, values: NDArray[np.float32]) -> NDArray[np.float64]: ...


@dataclass(frozen=True)
class RouteDecision:
    """Predicted route, confidence, and per-intent probabilities."""

    intent: str
    confidence: float
    scores: dict[str, float]


class KerasProbabilityClassifier:
    """Expose a saved Keras softmax model through the router classifier contract."""

    def __init__(self, model: object) -> None:
        self._model = model

    def predict_proba(self, values: NDArray[np.float32]) -> NDArray[np.float64]:
        predict = getattr(self._model, "predict", None)
        if predict is None:
            raise TypeError("loaded Keras artifact does not provide predict()")
        output = predict(values, verbose=0)
        probabilities = np.asarray(output, dtype=np.float64)
        if probabilities.ndim != 2:
            raise ValueError("Keras router artifact must return a probability matrix")
        return probabilities


class IntentRouter:
    """Classify a user request locally using pinned sentence embeddings."""

    def __init__(
        self,
        encoder: TextEncoder,
        classifier: ProbabilityClassifier,
        labels: tuple[str, ...],
    ) -> None:
        if len(labels) < 2 or len(set(labels)) != len(labels):
            raise ValueError("router labels must be unique and contain at least two intents")
        self._encoder = encoder
        self._classifier = classifier
        self._labels = labels

    def route(self, query: str) -> RouteDecision:
        """Return the highest-probability route for a non-empty user request."""
        if not query.strip():
            raise ValueError("router query must not be empty")
        embeddings = self._encoder.encode(
            [query], convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
        )
        if embeddings.ndim != 2 or embeddings.shape[0] != 1:
            raise ValueError("text encoder must return one embedding row per query")
        probabilities = self._classifier.predict_proba(embeddings)
        predicted = predict_labels(probabilities, labels=self._labels)
        if len(predicted) != 1:
            raise ValueError("router classifier must return one row per query")
        scores = {
            label: float(probabilities[0, index]) for index, label in enumerate(self._labels)
        }
        return RouteDecision(
            intent=predicted[0],
            confidence=scores[predicted[0]],
            scores=scores,
        )

    @classmethod
    def load(
        cls,
        report_path: Path = _REPORT_PATH,
        artifact_root: Path = _ARTIFACT_ROOT,
    ) -> "IntentRouter":
        """Load the promoted local model only after verifying its recorded SHA-256."""
        report = json.loads(report_path.read_text(encoding="utf-8"))
        selected = report["decision"]["selected_model"]
        artifact = report["artifacts"][selected]
        artifact_path = artifact_root / artifact["path"]
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if digest != artifact["sha256"]:
            raise ValueError("router artifact SHA-256 does not match the evaluation report")

        config = load_router_config()
        if selected == "logreg":
            bundle = joblib.load(artifact_path)
            if not isinstance(bundle, dict) or "classifier" not in bundle:
                raise ValueError("router Logistic Regression artifact has an invalid shape")
            classifier: ProbabilityClassifier = bundle["classifier"]
            labels = tuple(bundle["labels"])
        elif selected == "dnn":
            from tensorflow import keras

            model = keras.models.load_model(artifact_path, compile=False)
            classifier = KerasProbabilityClassifier(model)
            labels = config.labels
        else:
            raise ValueError(f"unsupported promoted router model: {selected}")

        if labels != config.labels:
            raise ValueError("router artifact labels do not match the pinned configuration")

        encoder = load_text_encoder(config)
        return cls(encoder, classifier, labels)
