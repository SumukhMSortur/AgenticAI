"""OpenAI SDK boundary for guarded external integrations."""

import httpx2
from openai import AsyncOpenAI


def create_openai_client(api_key: str, http_client: httpx2.AsyncClient) -> AsyncOpenAI:
    """Create an OpenAI client with the caller-supplied guarded HTTP transport."""
    return AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        http_client=http_client,
    )
