from fastapi.testclient import TestClient

from app.api.routes import health
from app.main import app


def test_health_returns_ok_when_database_is_available(monkeypatch) -> None:
    monkeypatch.setattr(health, "check_database_connection", lambda: True)

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "api": "ok",
        "database": "connected",
    }


def test_health_returns_unavailable_when_database_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(health, "check_database_connection", lambda: False)

    response = TestClient(app).get("/api/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unhealthy",
        "api": "ok",
        "database": "disconnected",
    }
    assert "password" not in response.text.lower()
