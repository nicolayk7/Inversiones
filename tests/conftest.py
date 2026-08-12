"""Shared pytest fixtures. Unit tests need none of this; integration tests (marked
`@pytest.mark.integration`) expect infra/docker-compose.yml to be up."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def api_client():
    from apps.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
