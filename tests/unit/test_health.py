"""
Smoke test for GET /health.
Mocks DB and Redis so this runs without live infrastructure.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


# Patch targets:
# - init_redis/close_redis: patch on app.main because main.py imports them directly
# - check_db/check_redis: patch on their source modules (called inside health endpoint)
_LIFESPAN_PATCHES = {
    "app.main.init_redis": AsyncMock,
    "app.main.close_redis": AsyncMock,
}


@pytest.fixture()
def client():
    with (
        patch("app.main.init_redis", new_callable=AsyncMock),
        patch("app.main.close_redis", new_callable=AsyncMock),
        patch("app.db.session.check_db", new_callable=AsyncMock, return_value=True),
        patch("app.db.redis.check_redis", new_callable=AsyncMock, return_value=True),
    ):
        with TestClient(app) as c:
            yield c


def test_health_returns_200_when_all_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["redis"] == "ok"
    assert "version" in body


def test_health_returns_503_when_db_down():
    with (
        patch("app.main.init_redis", new_callable=AsyncMock),
        patch("app.main.close_redis", new_callable=AsyncMock),
        patch("app.db.session.check_db", new_callable=AsyncMock, return_value=False),
        patch("app.db.redis.check_redis", new_callable=AsyncMock, return_value=True),
    ):
        with TestClient(app) as c:
            response = c.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["db"] == "error"


def test_health_returns_503_when_redis_down():
    with (
        patch("app.main.init_redis", new_callable=AsyncMock),
        patch("app.main.close_redis", new_callable=AsyncMock),
        patch("app.db.session.check_db", new_callable=AsyncMock, return_value=True),
        patch("app.db.redis.check_redis", new_callable=AsyncMock, return_value=False),
    ):
        with TestClient(app) as c:
            response = c.get("/health")
    assert response.status_code == 503
    assert response.json()["redis"] == "error"
