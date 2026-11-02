"""Small CPU-friendly recurrent model for factory risk sequences."""

from typing import cast

from torch import Tensor, nn


class RiskLSTM(nn.Module):
    """One-layer recurrent classifier whose output is an uncalibrated logit."""

    def __init__(self, feature_count: int, hidden_size: int) -> None:
        super().__init__()
        self.recurrent = nn.LSTM(feature_count, hidden_size, batch_first=True)
        self.classifier = nn.Linear(hidden_size, 1)

    def forward(self, sequence: Tensor) -> Tensor:
        """Map a normalized monthly sequence to one risk logit per factory."""
        _, (hidden, _) = self.recurrent(sequence)
        return cast(Tensor, self.classifier(hidden[-1]).squeeze(-1))
