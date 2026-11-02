"""Application configuration loaded via pydantic-settings."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for EcoChain Copilot."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General & Environment
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")
    PROJECT_NAME: str = Field(default="EcoChain Copilot")

    # Security & Auth
    SECRET_KEY: str = Field(
        default="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    )
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60)
    VAULT_ENCRYPTION_KEY: str = Field(default="dGVzdF92YXVsdF9lbmNyeXB0aW9uX2tleV8zMmJ5dGVzISE=")

    # Databases
    DATABASE_URL: str = Field(default="sqlite+pysqlite:///./test_ecochain.db")
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    CHROMA_PERSIST_DIRECTORY: Path = Field(default=Path("data/chroma_db"))

    # Cloud LLM (Gemini) - Model name must come from environment, never hardcoded
    GEMINI_API_KEY: str = Field(default="")
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash")

    # Local Privacy & OCR
    LLAMA_REDACTION_ENABLED: bool = Field(default=False)
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434")
    OLLAMA_MODEL: str = Field(default="llama3:8b-instruct-q4_K_M")
    TESSERACT_CMD: str = Field(default="")

    # Observability
    LANGSMITH_TRACING: bool = Field(default=False)
    LANGSMITH_API_KEY: str = Field(default="")
    LANGSMITH_PROJECT: str = Field(default="ecochain-copilot")

    # Verification & Risk Thresholds
    CONFIDENCE_THRESHOLD_DEFAULT: float = Field(default=0.85)
    CONFIDENCE_THRESHOLD_MODERATE_RISK: float = Field(default=0.90)
    CONFIDENCE_THRESHOLD_HIGH_RISK: float = Field(default=0.95)
    RISK_THRESHOLD_MODERATE: float = Field(default=0.30)
    RISK_THRESHOLD_HIGH: float = Field(default=0.60)
    EXPIRY_WARN_DAYS: int = Field(default=60)


settings = Settings()
