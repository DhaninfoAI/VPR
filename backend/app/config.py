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
    # Comma-separated list of sites web search may read for city/county research (subdomains included).
    # Keeps the model on code libraries and registries instead of unrelated pages. Blank = no filter.
    # OpenAI does not accept a bare TLD such as "gov"; the jurisdiction's own site is added per call
    # when it is known from earlier research. State-level research is not filtered.
    openai_allowed_domains: str = (
        "municode.com,ecode360.com,amlegal.com,codepublishing.com,municipal.codes,generalcode.com,"
        "gocodebook.com,safeguardproperties.com,prochamps.com"
    )

    @property
    def allowed_domains(self) -> list[str]:
        return [d.strip() for d in self.openai_allowed_domains.split(",") if d.strip()]
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
