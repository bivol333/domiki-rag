"""Central configuration loaded from .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Reads from .env automatically."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=True,
    )

    # API keys
    anthropic_api_key: str
    cohere_api_key: str

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # Models
    claude_model: str = "claude-sonnet-4-6"
    embedding_model: str = "embed-multilingual-v3.0"
    rerank_model: str = "rerank-multilingual-v3.0"

    # Collections
    public_collection: str = "domiki_public"
    private_collection: str = "domiki_private"


settings = Settings()
