"""Google GenAI SDK boundary for guarded Gemini integrations."""

from typing import Protocol, TypedDict

from google import genai
from google.genai import errors, types


class GeminiGenerateConfig(TypedDict, total=False):
    response_mime_type: str
    temperature: float
    max_output_tokens: int


class GeminiResponse(Protocol):
    @property
    def text(self) -> str | None: ...


class GeminiModels(Protocol):
    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: GeminiGenerateConfig,
    ) -> GeminiResponse: ...


class GeminiClient(Protocol):
    models: GeminiModels


class GeminiProviderError(Exception):
    """Raised when the Google GenAI SDK cannot complete a request."""


class GoogleGenAIModelsAdapter:
    def __init__(self, client: genai.Client) -> None:
        self._client = client

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: GeminiGenerateConfig,
    ) -> GeminiResponse:
        try:
            return self._client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(**config),
            )
        except errors.APIError as exc:
            raise GeminiProviderError from exc


class GoogleGenAIClientAdapter:
    def __init__(self, client: genai.Client) -> None:
        self.models: GeminiModels = GoogleGenAIModelsAdapter(client)


def create_gemini_client(api_key: str) -> GeminiClient:
    """Create the SDK-backed client inside the provider-only package boundary."""
    return GoogleGenAIClientAdapter(genai.Client(api_key=api_key))
