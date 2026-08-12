"""Requires infra/docker-compose.yml to be up (Postgres reachable on 5433, Redis on 6380).
Run with: pytest -m integration"""

import pytest

pytestmark = pytest.mark.integration


async def test_health_reports_ok(api_client):
    response = await api_client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["weights_version"] == "v1.0"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"
    assert body["checks"]["weights"] == "ok"
    assert body["status"] == "ok"
