"""Train, calibrate, evaluate, and promote the synthetic-data risk models."""

import argparse
import copy
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.risk.config import load_risk_config  # noqa: E402
from backend.app.risk.features import (  # noqa: E402
    FEATURE_NAMES,
    apply_standardizer,
    engineered_features,
    fit_standardizer,
    sequence_features,
)
from backend.app.risk.lstm import RiskLSTM  # noqa: E402
from backend.app.risk.promotion import select_promoted_model  # noqa: E402

DATA_DIR = ROOT / "data" / "synthetic"
DEFAULT_REPORT = ROOT / "reports" / "risk.json"
DEFAULT_ARTIFACT = ROOT / "artifacts" / "risk" / "risk_model_v1.joblib"
SPLIT_FILES = {
    "train": DATA_DIR / "audit_histories_train.json",
    "validation": DATA_DIR / "audit_histories_val.json",
    "test": DATA_DIR / "audit_histories_test.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _load_split(path: Path, window_months: int) -> tuple[np.ndarray, np.ndarray, list[str]]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    factories = payload["factories"]
    sequences = [
        sequence_features(factory["history"], window_months) for factory in factories
    ]
    labels = np.asarray(
        [int(factory["will_fail_next_6m"]) for factory in factories], dtype=np.int64
    )
    factory_ids = [str(factory["factory_id"]) for factory in factories]
    return np.stack(sequences), labels, factory_ids


def _logit(probabilities: np.ndarray) -> np.ndarray:
    """Convert probabilities to finite scores for Platt calibration."""
    clipped = np.clip(probabilities, 1e-7, 1.0 - 1e-7)
    return np.log(clipped / (1.0 - clipped))


def _calibrator(scores: np.ndarray, labels: np.ndarray, seed: int) -> LogisticRegression:
    model = LogisticRegression(max_iter=1000, random_state=seed)
    model.fit(scores.reshape(-1, 1), labels)
    return model


def _ece(probabilities: np.ndarray, labels: np.ndarray, bin_count: int) -> tuple[float, list[dict]]:
    edges = np.linspace(0.0, 1.0, bin_count + 1)
    expected_calibration_error = 0.0
    bins: list[dict] = []
    for index in range(bin_count):
        lower = edges[index]
        upper = edges[index + 1]
        selected = (probabilities >= lower) & (
            probabilities <= upper if index == bin_count - 1 else probabilities < upper
        )
        count = int(selected.sum())
        if count == 0:
            bins.append(
                {
                    "lower": round(float(lower), 8),
                    "upper": round(float(upper), 8),
                    "count": 0,
                    "mean_confidence": None,
                    "observed_rate": None,
                }
            )
            continue
        confidence = float(probabilities[selected].mean())
        observed = float(labels[selected].mean())
        expected_calibration_error += count / len(labels) * abs(confidence - observed)
        bins.append(
            {
                "lower": round(float(lower), 8),
                "upper": round(float(upper), 8),
                "count": count,
                "mean_confidence": round(confidence, 8),
                "observed_rate": round(observed, 8),
            }
        )
    return expected_calibration_error, bins


def _metrics(probabilities: np.ndarray, labels: np.ndarray, bin_count: int) -> dict:
    if len(np.unique(labels)) != 2:
        raise ValueError("risk evaluation split must contain both outcome classes")
    calibration_error, reliability = _ece(probabilities, labels, bin_count)
    return {
        "auroc": float(roc_auc_score(labels, probabilities)),
        "pr_auc": float(average_precision_score(labels, probabilities)),
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "ece": float(calibration_error),
        "reliability_curve": reliability,
    }


def _bootstrap_intervals(
    probabilities: np.ndarray,
    labels: np.ndarray,
    bin_count: int,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, dict[str, float | int]]:
    rng = np.random.default_rng(seed)
    samples: dict[str, list[float]] = {
        "auroc": [],
        "pr_auc": [],
        "brier_score": [],
        "ece": [],
    }
    for _ in range(bootstrap_samples):
        indices = rng.integers(0, len(labels), size=len(labels))
        sampled_labels = labels[indices]
        if len(np.unique(sampled_labels)) != 2:
            continue
        measured = _metrics(probabilities[indices], sampled_labels, bin_count)
        for name in samples:
            samples[name].append(float(measured[name]))
    if any(not values for values in samples.values()):
        raise ValueError("bootstrap could not produce valid confidence intervals")
    return {
        name: {
            "lower_95": float(np.quantile(values, 0.025)),
            "upper_95": float(np.quantile(values, 0.975)),
            "valid_replicates": len(values),
        }
        for name, values in samples.items()
    }


def _fit_lstm(
    training: np.ndarray,
    training_labels: np.ndarray,
    validation: np.ndarray,
    validation_labels: np.ndarray,
    *,
    hidden_size: int,
    max_epochs: int,
    patience: int,
    learning_rate: float,
    min_delta: float,
    seed: int,
) -> tuple[RiskLSTM, dict[str, Any]]:
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    model = RiskLSTM(training.shape[2], hidden_size)
    train_tensor = torch.as_tensor(training, dtype=torch.float32)
    train_target = torch.as_tensor(training_labels, dtype=torch.float32)
    validation_tensor = torch.as_tensor(validation, dtype=torch.float32)
    validation_target = torch.as_tensor(validation_labels, dtype=torch.float32)
    positive = max(1, int(training_labels.sum()))
    negative = len(training_labels) - positive
    loss_function = torch.nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([negative / positive], dtype=torch.float32)
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    best_loss = math.inf
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    epochs_without_improvement = 0
    for epoch in range(max_epochs):
        model.train()
        optimizer.zero_grad()
        train_loss = loss_function(model(train_tensor), train_target)
        train_loss.backward()
        optimizer.step()

        model.eval()
        with torch.no_grad():
            validation_loss = float(
                loss_function(model(validation_tensor), validation_target).item()
            )
        if validation_loss < best_loss - min_delta:
            best_loss = validation_loss
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = epoch + 1
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                break
    if best_state is None:
        raise RuntimeError("LSTM training did not produce a validation checkpoint")
    model.load_state_dict(best_state)
    return model, {"epochs_trained": epoch + 1, "best_epoch": best_epoch, "best_val_loss": best_loss}


def _round_metrics(metrics: dict) -> dict:
    rounded: dict[str, Any] = {}
    for key, value in metrics.items():
        if key == "reliability_curve":
            rounded[key] = value
        else:
            rounded[key] = round(float(value), 8)
    return rounded


def run_training(
    *,
    report_path: Path = DEFAULT_REPORT,
    artifact_path: Path = DEFAULT_ARTIFACT,
    source_git_sha: str | None = None,
) -> dict[str, Any]:
    """Train on factory-disjoint splits and write reproducible evaluation artifacts."""
    start = time.perf_counter()
    config = load_risk_config()
    np.random.seed(config.seed)
    torch.manual_seed(config.seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)

    loaded = {
        name: _load_split(path, config.feature_window_months)
        for name, path in SPLIT_FILES.items()
    }
    id_sets = {name: set(split[2]) for name, split in loaded.items()}
    if (
        id_sets["train"] & id_sets["validation"]
        or id_sets["train"] & id_sets["test"]
        or id_sets["validation"] & id_sets["test"]
    ):
        raise ValueError("factory IDs overlap across train, validation, and test splits")

    train_sequences, train_labels, _ = loaded["train"]
    validation_sequences, validation_labels, _ = loaded["validation"]
    test_sequences, test_labels, _ = loaded["test"]
    feature_count = len(FEATURE_NAMES)
    sequence_mean, sequence_scale = fit_standardizer(
        train_sequences.reshape(-1, feature_count)
    )
    normalized_sequences = {
        name: ((sequences - sequence_mean) / sequence_scale).astype(np.float32)
        for name, (sequences, _, _) in loaded.items()
    }
    engineered = {
        name: np.stack([engineered_features(sequence) for sequence in sequences])
        for name, (sequences, _, _) in loaded.items()
    }
    engineered_mean, engineered_scale = fit_standardizer(engineered["train"])
    normalized_engineered = {
        name: apply_standardizer(values, engineered_mean, engineered_scale)
        for name, values in engineered.items()
    }

    train_positive = int(train_labels.sum())
    train_negative = len(train_labels) - train_positive
    class_weight = train_negative / max(1, train_positive)
    estimators: dict[str, LogisticRegression | XGBClassifier] = {
        "logreg": LogisticRegression(
            C=config.logreg_c,
            class_weight="balanced",
            max_iter=1000,
            random_state=config.seed,
        ),
        "xgboost": XGBClassifier(
            n_estimators=config.xgboost_estimators,
            max_depth=config.xgboost_max_depth,
            learning_rate=config.xgboost_learning_rate,
            objective="binary:logistic",
            eval_metric="logloss",
            scale_pos_weight=class_weight,
            random_state=config.seed,
            n_jobs=1,
            tree_method="hist",
        ),
    }
    raw_scores: dict[str, dict[str, np.ndarray]] = {}
    calibrators: dict[str, LogisticRegression] = {}
    for name, estimator in estimators.items():
        estimator.fit(normalized_engineered["train"], train_labels)
        validation_scores = (
            estimator.decision_function(normalized_engineered["validation"])
            if name == "logreg"
            else _logit(estimator.predict_proba(normalized_engineered["validation"])[:, 1])
        )
        test_scores = (
            estimator.decision_function(normalized_engineered["test"])
            if name == "logreg"
            else _logit(estimator.predict_proba(normalized_engineered["test"])[:, 1])
        )
        calibrator = _calibrator(validation_scores, validation_labels, config.seed)
        calibrators[name] = calibrator
        raw_scores[name] = {"validation": validation_scores, "test": test_scores}

    lstm, lstm_training = _fit_lstm(
        normalized_sequences["train"],
        train_labels,
        normalized_sequences["validation"],
        validation_labels,
        hidden_size=config.lstm_hidden_size,
        max_epochs=config.lstm_epochs,
        patience=config.lstm_patience,
        learning_rate=config.lstm_learning_rate,
        min_delta=config.early_stopping_delta,
        seed=config.seed,
    )
    with torch.no_grad():
        validation_lstm_scores = lstm(
            torch.as_tensor(normalized_sequences["validation"], dtype=torch.float32)
        ).numpy()
        test_lstm_scores = lstm(
            torch.as_tensor(normalized_sequences["test"], dtype=torch.float32)
        ).numpy()
    calibrators["lstm"] = _calibrator(
        validation_lstm_scores, validation_labels, config.seed
    )
    raw_scores["lstm"] = {
        "validation": validation_lstm_scores,
        "test": test_lstm_scores,
    }

    validation_metrics: dict[str, dict[str, float]] = {}
    test_results: dict[str, dict[str, Any]] = {}
    for model_index, name in enumerate(("logreg", "xgboost", "lstm")):
        calibrator = calibrators[name]
        probabilities = {
            split_name: calibrator.predict_proba(
                raw_scores[name][split_name].reshape(-1, 1)
            )[:, 1]
            for split_name in ("validation", "test")
        }
        measured_validation = _metrics(
            probabilities["validation"], validation_labels, config.calibration_bins
        )
        validation_metrics[name] = {
            "auroc": measured_validation["auroc"],
            "brier_score": measured_validation["brier_score"],
        }
        measured_test = _metrics(probabilities["test"], test_labels, config.calibration_bins)
        test_results[name] = {
            "validation": _round_metrics(measured_validation),
            "test": _round_metrics(measured_test),
            "test_confidence_intervals": _bootstrap_intervals(
                probabilities["test"],
                test_labels,
                config.calibration_bins,
                config.bootstrap_samples,
                config.seed + model_index + 1,
            ),
        }

    selected_model, comparisons = select_promoted_model(
        validation_metrics,
        auroc_margin=config.promotion_auroc_margin,
        brier_margin=config.promotion_brier_margin,
    )
    bundle: dict[str, Any] = {
        "artifact_version": "1.0.0",
        "model_tag": selected_model,
        "feature_window_months": config.feature_window_months,
        "feature_count": feature_count,
        "sequence_mean": sequence_mean,
        "sequence_scale": sequence_scale,
        "engineered_mean": engineered_mean,
        "engineered_scale": engineered_scale,
        "calibrator": calibrators[selected_model],
        "baseline_comparison": validation_metrics,
    }
    if selected_model == "lstm":
        bundle["state_dict"] = copy.deepcopy(lstm.state_dict())
        bundle["lstm_hidden_size"] = config.lstm_hidden_size
    else:
        bundle["estimator"] = estimators[selected_model]

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, artifact_path, compress=3)
    artifact_sha256 = _sha256(artifact_path)
    split_summary = {
        name: {
            "factory_count": len(split[2]),
            "positive_count": int(split[1].sum()),
            "positive_rate": round(float(split[1].mean()), 8),
            "dataset_sha256": _sha256(SPLIT_FILES[name]),
        }
        for name, split in loaded.items()
    }
    report = {
        "report_version": "1.0.0",
        "evaluation": "synthetic_factory_disjoint_risk",
        "is_synthetic": True,
        "seed": config.seed,
        "source_git_sha": source_git_sha or _git_sha(),
        "config_sha256": _sha256(ROOT / "config" / "risk.yaml"),
        "feature_window_months": config.feature_window_months,
        "feature_names": list(FEATURE_NAMES),
        "features_exclude_targets_and_latent_labels": True,
        "split_summary": split_summary,
        "models": test_results,
        "promotion": {
            "served_model": selected_model,
            "comparison_split": "validation",
            "minimum_auroc_margin": config.promotion_auroc_margin,
            "minimum_brier_improvement": config.promotion_brier_margin,
            "lstm_beats_each_baseline": comparisons,
            "validation_metrics": validation_metrics,
        },
        "lstm_training": lstm_training,
        "compute_device": "cpu",
        "training_runtime_seconds": round(time.perf_counter() - start, 3),
        "artifact": {
            "version": bundle["artifact_version"],
            "path": str(artifact_path.relative_to(ROOT))
            if artifact_path.is_relative_to(ROOT)
            else str(artifact_path),
            "sha256": artifact_sha256,
        },
        "limitations": [
            "All outcomes and signals are synthetic and do not establish real-world validity.",
            "Calibration is fitted on the factory-disjoint validation split only.",
            "Promotion is selected on validation metrics; the test split is reporting-only.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args()
    report = run_training(report_path=args.report, artifact_path=args.artifact)
    print(
        f"Risk report: served={report['promotion']['served_model']}; "
        f"device={report['compute_device']}; "
        f"wrote {args.report}"
    )


if __name__ == "__main__":
    main()
