import time

import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth
from app.main import app


ORIGIN = "https://resqnet-eight-psi.vercel.app"
CLIENT_ID = "resqnet-test.apps.googleusercontent.com"
client = TestClient(app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def reset_auth_state(monkeypatch):
    auth.sessions.clear()
    monkeypatch.setattr(auth.settings, "google_client_id", None)
    monkeypatch.setattr(auth.settings, "cors_origins", ORIGIN)
    monkeypatch.setattr(auth.settings, "auth_cookie_secure", True)
    monkeypatch.setattr(auth.settings, "auth_cookie_samesite", "lax")
    yield
    auth.sessions.clear()


def _claims(**overrides):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-user-123",
        "email": "user@example.com",
        "email_verified": True,
        "name": "RESQNET User",
        "picture": "https://lh3.googleusercontent.com/photo.png",
        "exp": time.time() + 300,
    }
    claims.update(overrides)
    return claims


def _setup(monkeypatch, claims=None):
    monkeypatch.setattr(auth.settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(auth, "verify_google_credential", lambda credential, audience: claims or _claims())


def _issue_nonce():
    auth.settings.google_client_id = CLIENT_ID
    response = client.get("/api/auth/nonce", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    return response.json()["nonce"]


def test_auth_config_is_disabled_without_google_client_id():
    response = client.get("/api/auth/config")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "client_id": None}


def test_google_sign_in_requires_configuration_and_allowed_origin():
    missing_config = client.post(
        "/api/auth/google",
        json={"credential": "a-valid-looking-test-token-value"},
        headers={"Origin": ORIGIN},
    )
    assert missing_config.status_code == 503
    assert client.get("/api/auth/nonce", headers={"Origin": ORIGIN}).status_code == 503


def test_google_sign_in_rejects_unconfigured_origin(monkeypatch):
    _setup(monkeypatch)
    response = client.post(
        "/api/auth/google",
        json={"credential": "a-valid-looking-test-token-value"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403


def test_nonce_is_issued_only_to_an_allowed_origin(monkeypatch):
    monkeypatch.setattr(auth.settings, "google_client_id", CLIENT_ID)
    response = client.get("/api/auth/nonce", headers={"Origin": "https://attacker.example"})
    assert response.status_code == 403


def test_google_sign_in_rejects_nonce_mismatch(monkeypatch):
    nonce = _issue_nonce()
    _setup(monkeypatch, _claims(nonce="attacker-controlled-nonce"))
    response = client.post(
        "/api/auth/google",
        json={"credential": "a-valid-looking-test-token-value"},
        headers={"Origin": ORIGIN},
    )
    assert nonce
    assert response.status_code == 401


def test_google_sign_in_verifies_and_creates_http_only_session(monkeypatch):
    nonce = _issue_nonce()
    _setup(monkeypatch, _claims(nonce=nonce))
    response = client.post(
        "/api/auth/google",
        json={"credential": "a-valid-looking-test-token-value"},
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 200
    assert response.json()["user"] == {
        "sub": "google-user-123",
        "email": "user@example.com",
        "name": "RESQNET User",
        "picture": "https://lh3.googleusercontent.com/photo.png",
    }
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api/auth" in cookie
    assert "max-age=28800" in cookie
    assert "resqnet_login_nonce" in cookie
    assert response.headers["cache-control"] == "no-store"

    current = client.get("/api/auth/me")
    assert current.status_code == 200
    assert current.json()["user"]["sub"] == "google-user-123"
    replayed = client.post(
        "/api/auth/google",
        json={"credential": "a-valid-looking-test-token-value"},
        headers={"Origin": ORIGIN},
    )
    assert replayed.status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "another-client.apps.googleusercontent.com"},
        {"iss": "https://attacker.example"},
        {"exp": time.time() - 1},
        {"email_verified": False},
        {"aud": [CLIENT_ID, "another-client.apps.googleusercontent.com"], "azp": "another-client.apps.googleusercontent.com"},
    ],
)
def test_google_sign_in_rejects_wrong_audience_issuer_expiry_or_unverified_email(monkeypatch, overrides):
    nonce = _issue_nonce()
    claims = _claims(nonce=nonce, **overrides)
    _setup(monkeypatch, claims)
    response = client.post(
        "/api/auth/google",
        json={"credential": "a-valid-looking-test-token-value"},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_google_verifier_failure_does_not_create_a_session(monkeypatch):
    monkeypatch.setattr(auth.settings, "google_client_id", CLIENT_ID)
    _issue_nonce()

    def reject(_credential, _audience):
        raise auth.InvalidGoogleCredential

    monkeypatch.setattr(auth, "verify_google_credential", reject)
    response = client.post(
        "/api/auth/google",
        json={"credential": "a-valid-looking-test-token-value"},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_missing_google_verifier_fails_closed(monkeypatch):
    monkeypatch.setattr(auth.settings, "google_client_id", CLIENT_ID)
    _issue_nonce()

    def unavailable(_credential, _audience):
        raise auth.GoogleVerifierUnavailable

    monkeypatch.setattr(auth, "verify_google_credential", unavailable)
    response = client.post(
        "/api/auth/google",
        json={"credential": "a-valid-looking-test-token-value"},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 503
    assert "set-cookie" not in response.headers


def test_logout_revokes_session_and_clears_cookie(monkeypatch):
    nonce = _issue_nonce()
    _setup(monkeypatch, _claims(nonce=nonce))
    signed_in = client.post(
        "/api/auth/google",
        json={"credential": "a-valid-looking-test-token-value"},
        headers={"Origin": ORIGIN},
    )
    assert signed_in.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    signed_out = client.post("/api/auth/logout", headers={"Origin": ORIGIN})
    assert signed_out.status_code == 200
    assert signed_out.json() == {"ok": True}
    assert client.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected(monkeypatch):
    user = auth.UserResponse(sub="sub", email="user@example.com", name="User")
    session_id, _ = auth.sessions.create(user, now=100)
    assert auth.sessions.get(session_id, now=100 + auth.SESSION_TTL_SECONDS) is None


def test_login_nonce_is_one_time_and_expires():
    nonce = auth.sessions.create_nonce(now=100)
    assert auth.sessions.consume_nonce(nonce, now=100 + auth.NONCE_TTL_SECONDS) is False
    assert auth.sessions.consume_nonce(nonce) is False

    fresh = auth.sessions.create_nonce()
    assert auth.sessions.consume_nonce(fresh) is True
    assert auth.sessions.consume_nonce(fresh) is False


def test_auth_does_not_protect_health_or_simulation_demo_endpoints(monkeypatch):
    from app.api.routes import health

    monkeypatch.setattr(health, "check_database_connection", lambda: True)
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/simulations", json={"scenario_id": "earthquake"}).status_code == 201
