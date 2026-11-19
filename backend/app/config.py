from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str
    openai_api_key: str = ""
    openai_model: str = "gpt-5.5"
    # Leave blank for models that do not accept a reasoning effort.
    openai_reasoning_effort: str = "low"
    # low | medium | high - how much page text web search pulls in (high = slower, more tokens)
    openai_search_context: str = "medium"
    # Max tool calls (web searches) per research; 0 = no limit
    openai_max_tool_calls: int = 8
    # A saved jurisdiction rule older than this is re-researched on the next lookup.
    cache_ttl_days: int = 3
    # How many jurisdictions (state / county / city) are researched in parallel.
    research_concurrency: int = 3

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
