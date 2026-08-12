"""Health endpoint — checks DB, Redis, and that the frozen weights file loads and validates.
No auth required: used by orchestration/monitoring, never returns business data.

Responses only ever report generic status strings ("ok" / "error" / "degraded") — exception
detail is logged server-side (`logger.exception`) and never echoed back to the caller."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter

from packages.shared.config import settings
from packages.shared.weights import load_weights
from packages.storage.db import check_connection as check_db
from packages.storage.redis_client import check_connection as check_redis

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    checks: dict[str, str] = {}

    try:
        await check_db()
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 — health check must never raise
        logger.exception("database health check failed")
        checks["database"] = "error"

    try:
        await check_redis()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        logger.exception("redis health check failed")
        checks["redis"] = "error"

    try:
        load_weights(settings.weights_version)
        checks["weights"] = "ok"
    except Exception:  # noqa: BLE001
        logger.exception("weights health check failed")
        checks["weights"] = "error"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"

    return {
        "status": status,
        "checks": checks,
        "weights_version": settings.weights_version,
        "timestamp": datetime.now(UTC).isoformat(),
    }
