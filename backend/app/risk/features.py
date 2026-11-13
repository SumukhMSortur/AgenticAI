"""Leakage-aware feature construction for monthly factory audit histories."""

from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

FEATURE_NAMES = (
    "carbon_intensity",
    "labor_violations",
    "cert_lapse_days",
    "corrective_action_backlog",
    "safety_incidents",
)


def sequence_features(
    history: Sequence[Mapping[str, object]], window_months: int
) -> NDArray[np.float64]:
    """Return only the most recent observed signal window in chronological order."""
    if window_months < 2:
        raise ValueError("window_months must be at least 2")
    if len(history) < window_months:
        raise ValueError(f"history must contain at least {window_months} months")
    selected = history[-window_months:]
    months = [row.get("month") for row in selected]
    month_numbers = [
        month for month in months if isinstance(month, int) and not isinstance(month, bool)
    ]
    if len(month_numbers) != len(months):
        raise ValueError("history months must be consecutive integers")
    if any(
        following != current + 1
        for current, following in zip(month_numbers, month_numbers[1:], strict=False)
    ):
        raise ValueError("history months must be consecutive integers")
    rows: list[list[float]] = []
    for row in selected:
        values: list[float] = []
        for name in FEATURE_NAMES:
            raw_value = row.get(name)
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise ValueError(f"feature {name} must be a finite non-negative number")
            value = float(raw_value)
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"feature {name} must be a finite non-negative number")
            values.append(value)
        rows.append(values)
    return np.asarray(rows, dtype=np.float64)


def engineered_features(sequence: NDArray[np.float64]) -> NDArray[np.float64]:
    """Summarize last value, mean, variation, and trend for baseline models."""
    if sequence.ndim != 2 or sequence.shape[0] < 2 or sequence.shape[1] != len(FEATURE_NAMES):
        raise ValueError("sequence must have shape (months >= 2, five features)")
    time_axis = np.arange(sequence.shape[0], dtype=np.float64)
    centered_time = time_axis - time_axis.mean()
    denominator = float(np.dot(centered_time, centered_time))
    slopes = centered_time @ sequence / denominator
    return np.concatenate(
        (sequence[-1], sequence.mean(axis=0), sequence.std(axis=0), slopes)
    ).astype(np.float64, copy=False)


def fit_standardizer(
    training_values: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Fit normalization statistics on training samples only."""
    if training_values.ndim < 2 or training_values.shape[0] < 1:
        raise ValueError("training_values must contain at least one sample")
    means = training_values.mean(axis=0)
    scales = training_values.std(axis=0)
    scales = np.where(scales == 0.0, 1.0, scales)
    return means.astype(np.float64), scales.astype(np.float64)


def apply_standardizer(
    values: NDArray[np.float64],
    means: NDArray[np.float64],
    scales: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Apply previously fitted train-only normalization to any split."""
    if values.shape[1:] != means.shape or means.shape != scales.shape:
        raise ValueError("normalization statistics do not match feature dimensions")
    return ((values - means) / scales).astype(np.float64, copy=False)
