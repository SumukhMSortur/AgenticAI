"""Ragas faithfulness and answer-relevance metrics with local embeddings."""

import asyncio
from typing import Any

from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms.base import InstructorBaseRagasLLM
from ragas.metrics.collections import AnswerRelevancy, Faithfulness
from sentence_transformers import SentenceTransformer

from backend.app.rag.models import EMBED_MODEL_NAME


class LocalRagasEmbedding(BaseRagasEmbedding):
    """Ragas embedding adapter backed by the locally cached MiniLM model."""

    def __init__(self, model_name: str = EMBED_MODEL_NAME) -> None:
        super().__init__()
        self._model = SentenceTransformer(
            model_name,
            device="cpu",
            local_files_only=True,
        )

    def embed_text(self, text: str, **_kwargs: Any) -> list[float]:
        values = self._model.encode(text, show_progress_bar=False)
        return [float(value) for value in values]

    async def aembed_text(self, text: str, **_kwargs: Any) -> list[float]:
        return await asyncio.to_thread(self.embed_text, text)


class RagasMetricScorer:
    """Score each response with Ragas faithfulness and answer-relevance metrics."""

    def __init__(
        self,
        llm: InstructorBaseRagasLLM,
        embeddings: BaseRagasEmbedding,
        answer_relevancy_strictness: int = 1,
    ) -> None:
        self._faithfulness = Faithfulness(llm=llm)
        self._answer_relevancy = AnswerRelevancy(
            llm=llm,
            embeddings=embeddings,
            strictness=answer_relevancy_strictness,
        )

    async def score(
        self,
        query: str,
        response: str,
        retrieved_contexts: list[str],
    ) -> tuple[float, float]:
        faithfulness = await self._faithfulness.ascore(
            user_input=query,
            response=response,
            retrieved_contexts=retrieved_contexts,
        )
        answer_relevance = await self._answer_relevancy.ascore(
            user_input=query,
            response=response,
        )
        return float(faithfulness.value), float(answer_relevance.value)
