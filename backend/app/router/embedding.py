"""Offline-only loader for the pinned sentence embedding model."""

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from backend.app.router.config import RouterConfig


class PinnedTextEncoder:
    """Normalize SentenceTransformer's broad API to the router's typed encoder contract."""

    def __init__(self, model: SentenceTransformer) -> None:
        self._model = model

    def encode(
        self,
        sentences: list[str],
        *,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> NDArray[np.float32]:
        embeddings = self._model.encode(
            sentences,
            convert_to_numpy=convert_to_numpy,
            normalize_embeddings=normalize_embeddings,
            show_progress_bar=show_progress_bar,
        )
        return np.asarray(embeddings, dtype=np.float32)


def load_text_encoder(config: RouterConfig) -> PinnedTextEncoder:
    """Load the configured model revision from the local Hugging Face cache only."""
    model = SentenceTransformer(
        config.model_name,
        revision=config.model_revision,
        device="cpu",
        local_files_only=True,
    )
    return PinnedTextEncoder(model)
