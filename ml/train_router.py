"""Benchmark pinned sentence embeddings with Logistic Regression and a Keras DNN."""

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")

import joblib
import numpy as np
import tensorflow as tf
from sklearn.linear_model import LogisticRegression
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.router.config import load_router_config  # noqa: E402
from backend.app.router.embedding import load_text_encoder  # noqa: E402
from backend.app.router.evaluation import (  # noqa: E402
    QueryExample,
    classification_metrics,
    dnn_wins,
    predict_labels,
    stratified_splits,
)

DEFAULT_DATA = ROOT / "data" / "router_queries.json"
DEFAULT_REPORT = ROOT / "reports" / "router.json"
DEFAULT_ARTIFACT_ROOT = ROOT / "artifacts" / "router"
FAKE_LLM_SYSTEM_PROMPT = (
    "Classify the user's request into one configured EcoChain Copilot intent. "
    "Return only a JSON object with the intent."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _load_examples(path: Path, labels: tuple[str, ...]) -> list[QueryExample]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != set(labels):
        raise ValueError("router query data must contain exactly the configured intent labels")
    examples: list[QueryExample] = []
    seen_queries: set[str] = set()
    for label in labels:
        queries = payload[label]
        if not isinstance(queries, list):
            raise ValueError(f"queries for {label} must be a list")
        for index, query in enumerate(queries, start=1):
            if not isinstance(query, str) or not query.strip():
                raise ValueError(f"queries for {label} must be non-empty strings")
            normalized = query.strip().casefold()
            if normalized in seen_queries:
                raise ValueError("router query text must be unique")
            seen_queries.add(normalized)
            examples.append(QueryExample(f"{label}-{index:02d}", query.strip(), label))
    return examples


def _metrics_from_model(
    model: LogisticRegression | tf.keras.Model,
    values: np.ndarray,
    expected: list[str],
    labels: tuple[str, ...],
) -> dict[str, float]:
    if isinstance(model, LogisticRegression):
        probabilities = np.asarray(model.predict_proba(values), dtype=np.float64)
    else:
        probabilities = np.asarray(model.predict(values, verbose=0), dtype=np.float64)
    predicted = predict_labels(probabilities, labels=labels)
    return classification_metrics(expected, predicted, labels=labels)


def _latency(
    encoder: Any,
    model: LogisticRegression | tf.keras.Model,
    queries: list[str],
) -> dict[str, float | int]:
    def predict(query: str) -> None:
        embeddings = np.asarray(
            encoder.encode(
                [query],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )
        if isinstance(model, LogisticRegression):
            model.predict_proba(embeddings)
        else:
            model.predict(embeddings, verbose=0)

    predict(queries[0])
    durations: list[float] = []
    for query in queries:
        started = time.perf_counter()
        predict(query)
        durations.append((time.perf_counter() - started) * 1000.0)
    return {
        "p50_ms": float(np.percentile(durations, 50)),
        "p95_ms": float(np.percentile(durations, 95)),
        "samples": len(durations),
        "scope": "warm, single-query embedding plus classifier on CPU",
    }


def _fake_llm_accounting(
    tokenizer: Any,
    examples: list[QueryExample],
    *,
    input_rate: float,
    output_rate: float,
) -> dict[str, int | float]:
    input_tokens = 0
    output_tokens = 0
    for example in examples:
        prompt = f"{FAKE_LLM_SYSTEM_PROMPT}\nUser: {example.query}"
        completion = json.dumps({"intent": example.intent}, separators=(",", ":"))
        input_tokens += len(tokenizer.encode(prompt, add_special_tokens=True))
        output_tokens += len(tokenizer.encode(completion, add_special_tokens=False))
    cost = (
        input_tokens * input_rate / 1_000_000
        + output_tokens * output_rate / 1_000_000
    )
    return {
        "calls": len(examples),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_api_cost_usd": round(cost, 10),
    }


def train(
    *,
    data_path: Path = DEFAULT_DATA,
    report_path: Path = DEFAULT_REPORT,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
) -> dict[str, Any]:
    """Fit, compare, report, and persist only the validation-promoted classifier."""
    config = load_router_config()
    random.seed(config.seed)
    np.random.seed(config.seed)
    tf.keras.utils.set_random_seed(config.seed)
    tf.config.experimental.enable_op_determinism()
    torch_threads = 1
    import torch

    torch.set_num_threads(torch_threads)

    examples = _load_examples(data_path, config.labels)
    splits = stratified_splits(
        examples,
        labels=config.labels,
        test_fraction=config.test_fraction,
        validation_fraction=config.validation_fraction,
        seed=config.seed,
    )
    by_id = {example.query_id: example for example in examples}
    encoder = load_text_encoder(config)
    embeddings = np.asarray(
        encoder.encode(
            [example.query for example in examples],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ),
        dtype=np.float32,
    )
    if embeddings.shape != (len(examples), config.embedding_dimension):
        raise ValueError(
            f"embedding shape {embeddings.shape} does not match configured dimension "
            f"{config.embedding_dimension}"
        )
    embedding_by_id = {example.query_id: embeddings[index] for index, example in enumerate(examples)}
    label_indices = {label: index for index, label in enumerate(config.labels)}

    def split_data(name: str) -> tuple[np.ndarray, list[str], list[str]]:
        selected = [by_id[query_id] for query_id in splits[name]]
        return (
            np.stack([embedding_by_id[example.query_id] for example in selected]),
            [example.intent for example in selected],
            [example.query for example in selected],
        )

    train_values, train_labels, _ = split_data("train")
    validation_values, validation_labels, _ = split_data("validation")
    test_values, test_labels, test_queries = split_data("test")
    train_targets = np.asarray([label_indices[label] for label in train_labels], dtype=np.int64)

    baseline = LogisticRegression(
        C=config.logreg_c,
        max_iter=2000,
        random_state=config.seed,
    )
    baseline.fit(train_values, train_targets)

    dnn = tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(config.embedding_dimension,)),
            tf.keras.layers.Dense(config.dnn_hidden_units, activation="relu"),
            tf.keras.layers.Dropout(config.dnn_dropout),
            tf.keras.layers.Dense(len(config.labels), activation="softmax"),
        ]
    )
    dnn.compile(
        optimizer=tf.keras.optimizers.Adam(),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    early_stopping = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss",
        patience=config.dnn_patience,
        restore_best_weights=True,
    )
    dnn_history = dnn.fit(
        train_values,
        train_targets,
        validation_data=(
            validation_values,
            np.asarray([label_indices[label] for label in validation_labels], dtype=np.int64),
        ),
        epochs=config.dnn_epochs,
        batch_size=config.dnn_batch_size,
        callbacks=[early_stopping],
        verbose=0,
        shuffle=True,
    )

    baseline_validation = _metrics_from_model(
        baseline, validation_values, validation_labels, config.labels
    )
    dnn_validation = _metrics_from_model(dnn, validation_values, validation_labels, config.labels)
    selected_model = (
        "dnn"
        if dnn_wins(
            baseline_validation,
            dnn_validation,
            macro_f1_margin=config.promotion_macro_f1_margin,
        )
        else "logreg"
    )
    baseline_test = _metrics_from_model(baseline, test_values, test_labels, config.labels)
    dnn_test = _metrics_from_model(dnn, test_values, test_labels, config.labels)

    models: dict[str, LogisticRegression | tf.keras.Model] = {
        "logreg": baseline,
        "dnn": dnn,
    }
    latency = {
        name: _latency(encoder, model, test_queries) for name, model in models.items()
    }
    tokenizer = AutoTokenizer.from_pretrained(
        config.model_name,
        revision=config.model_revision,
        local_files_only=True,
    )
    test_examples = [by_id[query_id] for query_id in splits["test"]]
    llm_cost = _fake_llm_accounting(
        tokenizer,
        test_examples,
        input_rate=config.fake_llm_input_usd_per_million_tokens,
        output_rate=config.fake_llm_output_usd_per_million_tokens,
    )
    fake_cost = float(llm_cost["estimated_api_cost_usd"])
    local_cost_delta = 100.0 if fake_cost > 0 else 0.0

    artifact_root.mkdir(parents=True, exist_ok=True)
    if selected_model == "logreg":
        artifact_name = "router_logreg_v1.joblib"
        artifact_path = artifact_root / artifact_name
        joblib.dump(
            {"artifact_version": "1.0.0", "labels": list(config.labels), "classifier": baseline},
            artifact_path,
            compress=3,
        )
    else:
        artifact_name = "router_dnn_v1.keras"
        artifact_path = artifact_root / artifact_name
        dnn.save(artifact_path)

    report = {
        "evaluation": "hand_reviewed_stratified_intent_queries",
        "is_synthetic": False,
        "query_count": len(examples),
        "query_data_sha256": _sha256(data_path),
        "config_sha256": _sha256(ROOT / "config" / "router.yaml"),
        "source_git_sha": _git_sha(),
        "seed": config.seed,
        "splits": {
            "counts": {name: len(query_ids) for name, query_ids in splits.items()},
            "query_ids": splits,
            "label_counts": {
                name: {
                    label: sum(by_id[query_id].intent == label for query_id in query_ids)
                    for label in config.labels
                }
                for name, query_ids in splits.items()
            },
        },
        "embedding_model": {
            "name": config.model_name,
            "revision": config.model_revision,
            "license": "Apache-2.0",
            "license_evidence": "Model card metadata declares Apache-2.0; local-only load.",
            "dimensions": config.embedding_dimension,
            "device": "cpu",
            "normalization": "L2",
        },
        "intents": list(config.labels),
        "metrics": {
            "logreg": {"validation": baseline_validation, "test": baseline_test},
            "dnn": {"validation": dnn_validation, "test": dnn_test},
        },
        "latency": latency,
        "cost_comparison": {
            "scope": "test queries; token-priced external API only; local compute excluded",
            "fake_llm": llm_cost,
            "router_external_api_cost_usd": 0.0,
            "router_cost_delta_percent": local_cost_delta,
            "reference_rates_usd_per_million_tokens": {
                "input": config.fake_llm_input_usd_per_million_tokens,
                "output": config.fake_llm_output_usd_per_million_tokens,
            },
            "rates_are_illustrative_not_vendor_quotes": True,
            "accounting_note": (
                "Fake calls are cost-only references; output token counts use the gold route "
                "label and do not imply LLM classification accuracy."
            ),
        },
        "dnn_training": {
            "epochs_trained": len(dnn_history.history["loss"]),
            "batch_size": config.dnn_batch_size,
            "early_stopping_patience": config.dnn_patience,
        },
        "decision": {
            "selected_model": selected_model,
            "rule": (
                "Promote DNN only if validation macro-F1 improves by the configured margin "
                "and validation accuracy does not regress; otherwise serve Logistic Regression."
            ),
            "validation_macro_f1_margin": config.promotion_macro_f1_margin,
        },
        "artifacts": {
            selected_model: {
                "path": artifact_name,
                "sha256": _sha256(artifact_path),
                "version": "1.0.0",
            }
        },
        "limitations": [
            "Metrics reflect a small, manually authored query set and are not production accuracy claims.",
            "The pinned embedding model must already be cached; training and inference never access the network.",
            "Latency is warm single-query CPU inference and excludes process startup.",
            "The fake-LLM comparison estimates token-priced API spend; local compute and non-token costs are excluded.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    arguments = parser.parse_args()
    report = train(
        data_path=arguments.data,
        report_path=arguments.report,
        artifact_root=arguments.artifacts,
    )
    print(
        json.dumps(
            {
                "selected_model": report["decision"]["selected_model"],
                "metrics": report["metrics"],
                "report": str(arguments.report),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
