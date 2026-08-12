"""FastAPI application factory. Routers are the only HTTP boundary — they call into
packages/engines and packages/agents, never the other way around (architecture v1.0 §02)."""

from fastapi import FastAPI

from apps.api.routers import health, wealth
from packages.shared.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="Investment Intelligence API",
        version="0.1.0",
        description="Decision-support platform for wealth and trading analysis. Phase 1B MVP — "
        "Wealth Engine deterministic pipeline only; no agents, no other engines.",
    )
    app.include_router(health.router)
    app.include_router(wealth.router)
    return app


app = create_app()
