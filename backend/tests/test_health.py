from fastapi.testclient import TestClient

from app.api.routes import health
from app.core.config import Settings
from app.main import app


def test_demo_mode_uses_sqlite_only_when_database_url_is_missing() -> None:
    demo_settings = Settings(
        _env_file=None,
        database_url=None,
        resqnet_demo_mode=True,
    )
    assert demo_settings.effective_database_url == "sqlite+pysqlite:///./resqnet-demo.sqlite3"

    configured_settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://db.example/resqnet",
        resqnet_demo_mode=True,
    )
    assert configured_settings.effective_database_url == (
        "postgresql+psycopg://db.example/resqnet"
    )


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
