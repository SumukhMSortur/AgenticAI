"""Tests for stratified intent evaluation and local router inference."""

import json
from pathlib import Path

import numpy as np
import pytest

from backend.app.router.config import RouterConfig, load_router_config
from backend.app.router.evaluation import (
    QueryExample,
    classification_metrics,
    dnn_wins,
    predict_labels,
    stratified_splits,
)
from backend.app.router.intent import (
    IntentRouter,
    KerasProbabilityClassifier,
    RouteDecision,
)
from ml.train_router import DEFAULT_DATA, _load_examples


class FakeEncoder:
    def __init__(self, *, malformed: bool = False) -> None:
        self.malformed = malformed

    def encode(
        self,
        sentences: list[str],
        *,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        _ = (convert_to_numpy, normalize_embeddings, show_progress_bar)
        if self.malformed:
            return np.asarray([1.0], dtype=np.float32)
        return np.ones((len(sentences), 3), dtype=np.float32)


class FakeClassifier:
    def predict_proba(self, values: np.ndarray) -> np.ndarray:
        assert values.shape == (1, 3)
        return np.asarray([[0.1, 0.9]], dtype=np.float64)


class FakeKerasModel:
    def predict(self, _values: np.ndarray, *, verbose: int = 0) -> list[list[float]]:
        del verbose
        return [[0.3, 0.7]]


def test_router_config_and_stratified_splits_are_valid_and_reproducible() -> None:
    config = load_router_config()
    assert config.model_revision == "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    examples = _load_examples(DEFAULT_DATA, config.labels)
    assert len(examples) == 144
    assert {example.intent for example in examples} == set(config.labels)
    assert all(len([row for row in examples if row.intent == label]) == 24 for label in config.labels)

    first = stratified_splits(
        examples,
        labels=config.labels,
        test_fraction=config.test_fraction,
        validation_fraction=config.validation_fraction,
        seed=config.seed,
    )
    second = stratified_splits(
        examples,
        labels=config.labels,
        test_fraction=config.test_fraction,
        validation_fraction=config.validation_fraction,
        seed=config.seed,
    )
    assert first == second
    assert set(first["train"]).isdisjoint(first["validation"])
    assert set(first["train"]).isdisjoint(first["test"])
    assert set(first["validation"]).isdisjoint(first["test"])
    assert len(first["train"]) + len(first["validation"]) + len(first["test"]) == len(examples)
    by_id = {example.query_id: example for example in examples}
    for split_ids in first.values():
        counts = {
            label: sum(by_id[query_id].intent == label for query_id in split_ids)
            for label in config.labels
        }
        assert max(counts.values()) - min(counts.values()) <= 1


def test_router_config_rejects_bad_labels_and_fraction_totals() -> None:
    config = load_router_config()
    with pytest.raises(ValueError):
        RouterConfig.model_validate({**config.model_dump(), "labels": ("same", "same")})
    with pytest.raises(ValueError):
        RouterConfig.model_validate(
            {**config.model_dump(), "test_fraction": 0.5, "validation_fraction": 0.5}
        )


def test_split_validation_rejects_incomplete_or_duplicate_examples() -> None:
    labels = ("one", "two")
    repeated = [
        QueryExample("same", "query one", "one"),
        QueryExample("same", "query two", "two"),
        QueryExample("three", "query three", "one"),
    ]
    with pytest.raises(ValueError, match="IDs must be unique"):
        stratified_splits(
            repeated,
            labels=labels,
            test_fraction=0.2,
            validation_fraction=0.2,
            seed=42,
        )
    with pytest.raises(ValueError, match="every configured"):
        stratified_splits(
            [QueryExample("one", "only one", "one")],
            labels=labels,
            test_fraction=0.2,
            validation_fraction=0.2,
            seed=42,
        )
    with pytest.raises(ValueError, match="at least three"):
        stratified_splits(
            [
                QueryExample("one-a", "one a", "one"),
                QueryExample("one-b", "one b", "one"),
                QueryExample("one-c", "one c", "one"),
                QueryExample("two-a", "two a", "two"),
                QueryExample("two-b", "two b", "two"),
            ],
            labels=labels,
            test_fraction=0.2,
            validation_fraction=0.2,
            seed=42,
        )


def test_classification_metrics_and_validation_only_dnn_promotion() -> None:
    labels = ("certificate", "risk")
    metrics = classification_metrics(
        ["certificate", "risk", "risk"],
        ["certificate", "certificate", "risk"],
        labels=labels,
    )
    assert metrics["accuracy"] == pytest.approx(2 / 3)
    assert metrics["macro_f1"] == pytest.approx(2 / 3)
    assert dnn_wins(
        {"accuracy": 0.8, "macro_f1": 0.78},
        {"accuracy": 0.8, "macro_f1": 0.80},
        macro_f1_margin=0.01,
    )
    assert not dnn_wins(
        {"accuracy": 0.8, "macro_f1": 0.78},
        {"accuracy": 0.7, "macro_f1": 0.95},
        macro_f1_margin=0.01,
    )
    assert not dnn_wins(
        {"accuracy": 0.8, "macro_f1": 0.78},
        {"accuracy": 0.8, "macro_f1": 0.78},
        macro_f1_margin=0.01,
    )
    with pytest.raises(ValueError, match="equal non-zero"):
        classification_metrics([], [], labels=labels)
    with pytest.raises(ValueError, match="configured"):
        classification_metrics(["unknown"], ["unknown"], labels=labels)
    with pytest.raises(ValueError, match="non-negative"):
        dnn_wins({}, {}, macro_f1_margin=-0.1)
    with pytest.raises(ValueError, match="include accuracy"):
        dnn_wins({}, {}, macro_f1_margin=0.0)


def test_probability_label_mapping_validates_shape_and_values() -> None:
    assert predict_labels(
        np.asarray([[0.2, 0.8], [0.9, 0.1]], dtype=np.float64),
        labels=("first", "second"),
    ) == ["second", "first"]
    with pytest.raises(ValueError, match="columns"):
        predict_labels(np.asarray([[0.2]], dtype=np.float64), labels=("one", "two"))
    with pytest.raises(ValueError, match="finite"):
        predict_labels(np.asarray([[np.nan, 0.5]]), labels=("one", "two"))


def test_intent_router_and_keras_adapter_produce_route_decisions() -> None:
    router = IntentRouter(FakeEncoder(), FakeClassifier(), ("lookup", "review"))
    decision = router.route("Please check the review status.")
    assert decision == RouteDecision(
        intent="review",
        confidence=0.9,
        scores={"lookup": 0.1, "review": 0.9},
    )
    keras_classifier = KerasProbabilityClassifier(FakeKerasModel())
    assert np.array_equal(
        keras_classifier.predict_proba(np.ones((1, 2), dtype=np.float32)),
        np.asarray([[0.3, 0.7]]),
    )
    with pytest.raises(ValueError, match="not be empty"):
        router.route("  ")
    with pytest.raises(ValueError, match="embedding row"):
        IntentRouter(FakeEncoder(malformed=True), FakeClassifier(), ("lookup", "review")).route(
            "hello"
        )


def test_intent_router_rejects_invalid_classifier_output() -> None:
    class NonFiniteClassifier:
        def predict_proba(self, _values: np.ndarray) -> np.ndarray:
            return np.asarray([[0.5, np.nan]])

    with pytest.raises(ValueError, match="finite"):
        IntentRouter(FakeEncoder(), NonFiniteClassifier(), ("lookup", "review")).route("query")

    class InvalidKerasModel:
        def predict(self, _values: np.ndarray, *, verbose: int = 0) -> list[float]:
            del verbose
            return [0.2, 0.8]

    with pytest.raises(ValueError, match="probability matrix"):
        KerasProbabilityClassifier(InvalidKerasModel()).predict_proba(
            np.ones((1, 2), dtype=np.float32)
        )


def test_router_artifact_loader_rejects_hash_mismatch(tmp_path: Path) -> None:
    report_path = tmp_path / "router.json"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / "model.joblib").write_bytes(b"not-a-model")
    report_path.write_text(
        json.dumps(
            {
                "decision": {"selected_model": "logreg"},
                "artifacts": {
                    "logreg": {"path": "model.joblib", "sha256": "wrong-hash"}
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="SHA-256"):
        IntentRouter.load(report_path, artifact_root)


def test_router_data_rejects_duplicate_and_unconfigured_queries(tmp_path: Path) -> None:
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(
        json.dumps({"one": ["same", "SAME"], "two": ["other"]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique"):
        _load_examples(duplicate_path, ("one", "two"))
    missing_path = tmp_path / "missing.json"
    missing_path.write_text(json.dumps({"one": ["one"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly"):
        _load_examples(missing_path, ("one", "two"))
