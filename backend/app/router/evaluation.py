"""Data splitting, scoring, and validation-only model promotion for the router."""

from collections import Counter
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split


@dataclass(frozen=True)
class QueryExample:
    """A manually reviewed request and its expected route."""

    query_id: str
    query: str
    intent: str


def stratified_splits(
    examples: list[QueryExample],
    *,
    labels: tuple[str, ...],
    test_fraction: float,
    validation_fraction: float,
    seed: int,
) -> dict[str, list[str]]:
    """Create reproducible train/validation/test splits without losing class balance."""
    if not examples:
        raise ValueError("router query set must not be empty")
    identifiers = [example.query_id for example in examples]
    intents = [example.intent for example in examples]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("router query IDs must be unique")
    if set(intents) != set(labels):
        raise ValueError("router query set must contain every configured intent")
    counts = Counter(intents)
    if any(counts[label] < 3 for label in labels):
        raise ValueError("each router intent needs at least three examples")
    if not 0.0 < test_fraction < 0.5 or not 0.0 < validation_fraction < 0.5:
        raise ValueError("split fractions must be between zero and one half")
    if test_fraction + validation_fraction >= 1.0:
        raise ValueError("split fractions must leave training data")

    indices = np.arange(len(examples))
    training_indices, remainder_indices = train_test_split(
        indices,
        test_size=test_fraction + validation_fraction,
        random_state=seed,
        stratify=intents,
    )
    remainder_intents = [intents[index] for index in remainder_indices]
    test_share = test_fraction / (test_fraction + validation_fraction)
    validation_indices, test_indices = train_test_split(
        remainder_indices,
        test_size=test_share,
        random_state=seed + 1,
        stratify=remainder_intents,
    )
    return {
        "train": [identifiers[index] for index in training_indices],
        "validation": [identifiers[index] for index in validation_indices],
        "test": [identifiers[index] for index in test_indices],
    }


def classification_metrics(
    expected: list[str], predicted: list[str], *, labels: tuple[str, ...]
) -> dict[str, float]:
    """Return class-balanced accuracy and macro-F1 for a fixed label set."""
    if not expected or len(expected) != len(predicted):
        raise ValueError("expected and predicted labels must have equal non-zero length")
    if any(label not in labels for label in expected + predicted):
        raise ValueError("all labels must be configured router intents")
    return {
        "accuracy": float(accuracy_score(expected, predicted)),
        "macro_f1": float(
            f1_score(expected, predicted, labels=list(labels), average="macro", zero_division=0)
        ),
    }


def dnn_wins(
    baseline: dict[str, float],
    candidate: dict[str, float],
    *,
    macro_f1_margin: float,
) -> bool:
    """Promote the DNN only when validation F1 improves and accuracy does not regress."""
    if macro_f1_margin < 0.0:
        raise ValueError("promotion macro-F1 margin must be non-negative")
    required = ("accuracy", "macro_f1")
    if any(name not in metrics for metrics in (baseline, candidate) for name in required):
        raise ValueError("promotion metrics must include accuracy and macro_f1")
    return (
        candidate["macro_f1"] >= baseline["macro_f1"] + macro_f1_margin
        and candidate["accuracy"] >= baseline["accuracy"]
    )


def predict_labels(
    probabilities: NDArray[np.float64], *, labels: tuple[str, ...]
) -> list[str]:
    """Map a class-probability matrix into configured route labels."""
    if probabilities.ndim != 2 or probabilities.shape[1] != len(labels):
        raise ValueError("probability columns must match configured labels")
    if not np.isfinite(probabilities).all():
        raise ValueError("router probabilities must be finite")
    return [labels[index] for index in probabilities.argmax(axis=1)]
