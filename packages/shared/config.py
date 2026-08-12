"""Application settings, loaded from environment / .env. See .env.example."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"

    # Ports 5433/6380, not the 5432/6379 defaults — this machine already runs an unrelated
    # Postgres/Redis stack on the standard ports (see infra/docker-compose.yml).
    database_url: str = "postgresql+asyncpg://ii:ii@localhost:5433/investment_intelligence"
    redis_url: str = "redis://localhost:6380/0"

    # MVP is mono-user (architecture v1.0, decision #12) — a single API key is enough.
    api_key: str = "dev-local-key"

    # Unused until Phase 1+ agents exist. Optional so Phase 0 runs without it.
    anthropic_api_key: str | None = None

    # Which frozen weights file (config/weights/{version}.yaml) engines load. Never changed at
    # runtime by an agent — see packages/shared/weights.py.
    weights_version: str = "v1.0"

    # SEC EDGAR's fair-access policy requires a descriptive User-Agent identifying the requester
    # (https://www.sec.gov/os/webmaster-faq#developers) — NOT an API key/secret, just a required
    # header. See packages/providers/fundamentals/sec_edgar.py (Phase 1B first live integration).
    sec_edgar_user_agent: str = "investment-intelligence-dev (set SEC_EDGAR_USER_AGENT in .env)"

    # Massive (formerly Polygon.io) MarketDataProvider — Phase 3 of Market Data Foundation. A real
    # secret (query-param API key), unlike sec_edgar_user_agent above. Optional so the app/tests
    # run without it; packages/providers/market/massive.py raises MassiveAuthError at construction
    # if a caller actually tries to use the provider with none configured.
    massive_api_key: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
