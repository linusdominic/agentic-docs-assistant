from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Provider SDKs read their keys (ANTHROPIC_API_KEY, ...) from the process environment,
# so export the local .env file as well as feeding it to Settings below.
load_dotenv()


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5433/docs_agent"

    # Any LangChain chat model string, "provider:model". Swap providers without code changes.
    llm_model: str = "anthropic:claude-opus-5-5"
    llm_max_tokens: int = 16000

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    retrieval_k: int = 4
    chunk_max_chars: int = 900

    # When set, every /chat request must send this value in the X-API-Key header.
    api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
