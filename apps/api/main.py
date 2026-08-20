"""FastAPI application factory. Routers are the only HTTP boundary — they call into
packages/engines and packages/agents, never the other way around (architecture v1.0 §02)."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from apps.api.routers import health, wealth
from packages.shared.logging import configure_logging

_WEB_DIR = Path(__file__).resolve().parents[2] / "apps" / "web"


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
    # Minimal, static, no-build-step MVP dashboard (apps/web/index.html) — same-origin under the
    # API app itself, so it calls /v1/wealth/compute directly with no CORS setup needed. Purely a
    # static file mount; it contains no business logic and imports nothing from packages/.
    app.mount("/dashboard", StaticFiles(directory=_WEB_DIR, html=True), name="dashboard")
    return app


app = create_app()
