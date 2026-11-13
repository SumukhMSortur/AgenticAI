"""Validated CPU training and risk evaluation settings."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "risk.yaml"


class RiskConfig(BaseModel):
    """Thresholds and training limits that affect risk model behavior."""

    seed: int = Field(ge=0)
    feature_window_months: int = Field(ge=2)
    calibration_bins: int = Field(ge=2)
    bootstrap_samples: int = Field(gt=0)
    logreg_c: float = Field(gt=0.0)
    xgboost_estimators: int = Field(gt=0)
    xgboost_max_depth: int = Field(gt=0)
    xgboost_learning_rate: float = Field(gt=0.0, le=1.0)
    lstm_hidden_size: int = Field(gt=0)
    lstm_epochs: int = Field(gt=0)
    lstm_patience: int = Field(gt=0)
    lstm_learning_rate: float = Field(gt=0.0)
    early_stopping_delta: float = Field(ge=0.0)
    promotion_auroc_margin: float = Field(ge=0.0, le=1.0)
    promotion_brier_margin: float = Field(ge=0.0, le=1.0)


def load_risk_config(path: Path = _CONFIG_PATH) -> RiskConfig:
    """Load and validate the single source of risk training thresholds."""
    with path.open(encoding="utf-8") as config_file:
        settings: Any = yaml.safe_load(config_file)
    if not isinstance(settings, dict):
        raise ValueError(f"Risk configuration must be a mapping: {path}")
    return RiskConfig.model_validate(settings)
