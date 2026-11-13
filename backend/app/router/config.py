"""Validated intent-router model and benchmark settings."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "router.yaml"


class RouterConfig(BaseModel):
    """Pinned model, training, promotion, and cost-reference settings."""

    seed: int = Field(ge=0)
    model_name: str = Field(min_length=1)
    model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    embedding_dimension: int = Field(gt=0)
    labels: tuple[str, ...] = Field(min_length=2)
    test_fraction: float = Field(gt=0.0, lt=0.5)
    validation_fraction: float = Field(gt=0.0, lt=0.5)
    logreg_c: float = Field(gt=0.0)
    dnn_hidden_units: int = Field(gt=0)
    dnn_dropout: float = Field(ge=0.0, lt=1.0)
    dnn_epochs: int = Field(gt=0)
    dnn_batch_size: int = Field(gt=0)
    dnn_patience: int = Field(gt=0)
    promotion_macro_f1_margin: float = Field(ge=0.0, le=1.0)
    fake_llm_input_usd_per_million_tokens: float = Field(ge=0.0)
    fake_llm_output_usd_per_million_tokens: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_fractions_and_labels(self) -> "RouterConfig":
        if self.test_fraction + self.validation_fraction >= 1.0:
            raise ValueError("test and validation fractions must leave training data")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("router labels must be unique")
        return self


def load_router_config(path: Path = _CONFIG_PATH) -> RouterConfig:
    """Load and validate the single source of router training settings."""
    with path.open(encoding="utf-8") as config_file:
        settings: Any = yaml.safe_load(config_file)
    if not isinstance(settings, dict):
        raise ValueError(f"Router configuration must be a mapping: {path}")
    return RouterConfig.model_validate(settings)
