"""Guarded OpenAI client adapter for Ragas evaluation."""

import json
import os

import httpx2 as httpx
from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.llms.base import InstructorBaseRagasLLM
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.errors import PrivacyViolationError
from backend.app.privacy.outbound_guard import (
    ExternalCallPolicy,
    OutboundGuard,
    outbound_guard,
)

_OPENAI_REQUEST_FIELDS = {
    "model",
    "messages",
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "response_format",
    "stream",
    "seed",
    "stop",
    "frequency_penalty",
    "presence_penalty",
    "n",
    "logit_bias",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
}


class GuardedOpenAIRagasJudge:
    """Construct a Ragas judge whose every OpenAI request passes through OutboundGuard."""

    def __init__(
        self,
        model: str,
        tenant_id: str,
        tenant_opted_in: bool,
        db: Session | None = None,
        guard: OutboundGuard | None = None,
    ) -> None:
        if not tenant_opted_in:
            raise PrivacyViolationError("External Ragas judging requires explicit tenant opt-in.")
        if not tenant_id.strip():
            raise PrivacyViolationError("Tenant ID is required for external Ragas judging.")
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the configured Ragas judge.")

        self.tenant_id = tenant_id
        self.db = db
        self.guard = guard or outbound_guard
        self.policy = ExternalCallPolicy(
            provider="openai",
            tenant_opted_in=tenant_opted_in,
            allowlisted_fields=_OPENAI_REQUEST_FIELDS,
            max_payload_chars=30_000,
        )
        self.http_client = httpx.AsyncClient(
            timeout=60.0,
            event_hooks={"request": [self._guard_request]},
        )
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            http_client=self.http_client,
        )
        os.environ["RAGAS_DO_NOT_TRACK"] = "true"
        self.llm: InstructorBaseRagasLLM = llm_factory(
            model,
            provider="openai",
            client=self.client,
            adapter="instructor",
            temperature=0.0,
        )

    async def _guard_request(self, request: httpx.Request) -> None:
        if request.url.host != "api.openai.com":
            raise PrivacyViolationError("Ragas judge request targeted an unapproved host.")
        try:
            payload = json.loads(request.content)
        except json.JSONDecodeError as exc:
            raise PrivacyViolationError("Ragas judge request was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise PrivacyViolationError("Ragas judge request payload must be a JSON object.")

        self.guard.verify_and_log_external_call(
            provider="openai",
            fields_payload=payload,
            policy=self.policy,
            tenant_id=self.tenant_id,
            db=self.db,
        )

    async def aclose(self) -> None:
        await self.client.close()
