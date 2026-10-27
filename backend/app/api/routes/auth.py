"""Google sign-in and short-lived, revocable browser sessions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings

router = APIRouter()

SESSION_COOKIE = "resqnet_session"
NONCE_COOKIE = "resqnet_login_nonce"
SESSION_TTL_SECONDS = 8 * 60 * 60
NONCE_TTL_SECONDS = 5 * 60
SESSION_COOKIE_PATH = "/api/auth"


class GoogleSignInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: str = Field(min_length=20, max_length=16_384)


class UserResponse(BaseModel):
    sub: str
    email: str
    name: str
    picture: str | None = None


@dataclass(frozen=True)
class Session:
    user: UserResponse
    expires_at: float


class SessionStore:
    """Process-local session registry; opaque IDs are stored only as SHA-256 digests."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._nonces: dict[str, float] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    def create(self, user: UserResponse, now: float | None = None) -> tuple[str, Session]:
        timestamp = time.time() if now is None else now
        session_id = secrets.token_urlsafe(32)
        session = Session(user=user, expires_at=timestamp + SESSION_TTL_SECONDS)
        with self._lock:
            self._prune(timestamp)
            self._sessions[self._key(session_id)] = session
        return session_id, session

    def get(self, session_id: str | None, now: float | None = None) -> Session | None:
        if not session_id:
            return None
        timestamp = time.time() if now is None else now
        key = self._key(session_id)
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if session.expires_at <= timestamp:
                self._sessions.pop(key, None)
                return None
            return session

    def revoke(self, session_id: str | None) -> None:
        if session_id:
            with self._lock:
                self._sessions.pop(self._key(session_id), None)

    def create_nonce(self, now: float | None = None) -> str:
        timestamp = time.time() if now is None else now
        nonce = secrets.token_urlsafe(32)
        with self._lock:
            self._prune(timestamp)
            self._nonces[self._key(nonce)] = timestamp + NONCE_TTL_SECONDS
        return nonce

    def consume_nonce(self, nonce: str | None, now: float | None = None) -> bool:
        if not nonce:
            return False
        timestamp = time.time() if now is None else now
        with self._lock:
            expires_at = self._nonces.pop(self._key(nonce), None)
            return expires_at is not None and expires_at > timestamp

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._nonces.clear()

    def _prune(self, now: float) -> None:
        expired = [key for key, value in self._sessions.items() if value.expires_at <= now]
        for key in expired:
            self._sessions.pop(key, None)
        expired_nonces = [key for key, expiry in self._nonces.items() if expiry <= now]
        for key in expired_nonces:
            self._nonces.pop(key, None)


sessions = SessionStore()


class InvalidGoogleCredential(Exception):
    pass


class GoogleVerifierUnavailable(Exception):
    pass


def verify_google_credential(credential: str, audience: str) -> dict[str, Any]:
    """Verify the JWT signature and standard Google ID-token claims using google-auth."""
    try:
        from google.auth.exceptions import GoogleAuthError, TransportError
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token
    except ImportError as exc:
        raise GoogleVerifierUnavailable from exc

    try:
        return id_token.verify_oauth2_token(
            credential,
            GoogleRequest(),
            audience=audience,
        )
    except TransportError as exc:
        raise GoogleVerifierUnavailable from exc
    except (ValueError, GoogleAuthError) as exc:
        raise InvalidGoogleCredential from exc
    except Exception as exc:
        # Unexpected verification-library failures must never turn into a session.
        raise GoogleVerifierUnavailable from exc


def _user_from_claims(claims: dict[str, Any], audience: str, nonce: str) -> UserResponse:
    issuer = claims.get("iss")
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        raise InvalidGoogleCredential

    token_audience = claims.get("aud")
    audiences = token_audience if isinstance(token_audience, list) else [token_audience]
    if audience not in audiences:
        raise InvalidGoogleCredential
    if claims.get("azp") is not None and claims["azp"] != audience:
        raise InvalidGoogleCredential
    if isinstance(token_audience, list) and len(token_audience) > 1 and claims.get("azp") != audience:
        raise InvalidGoogleCredential
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise InvalidGoogleCredential

    expires_at = claims.get("exp")
    if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
        raise InvalidGoogleCredential
    if expires_at <= time.time():
        raise InvalidGoogleCredential

    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise InvalidGoogleCredential
    if not isinstance(email, str) or not email or len(email) > 320:
        raise InvalidGoogleCredential
    if claims.get("email_verified") is not True:
        raise InvalidGoogleCredential

    name = claims.get("name")
    if not isinstance(name, str) or not name.strip():
        name = email
    picture = claims.get("picture")
    if not isinstance(picture, str) or not _is_google_picture_url(picture):
        picture = None

    return UserResponse(
        sub=subject,
        email=email,
        name=name.strip()[:200],
        picture=picture,
    )


def _is_google_picture_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and (host == "googleusercontent.com" or host.endswith(".googleusercontent.com"))
    )


def _require_allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    configured = {item.rstrip("/") for item in settings.allowed_cors_origins}
    if origin is None or origin.rstrip("/") not in configured:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed.",
        )


def _authentication_not_configured() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Google authentication is not configured.",
    )


def _session_for_request(request: Request) -> Session | None:
    return sessions.get(request.cookies.get(SESSION_COOKIE))


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        max_age=SESSION_TTL_SECONDS,
        path=SESSION_COOKIE_PATH,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
    response.headers["Cache-Control"] = "no-store"


def _clear_nonce_cookie(response: Response) -> None:
    response.delete_cookie(
        key=NONCE_COOKIE,
        path=SESSION_COOKIE_PATH,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )


@router.get("/config")
def get_auth_config() -> dict[str, Any]:
    client_id = settings.google_client_id
    return {"enabled": bool(client_id), "client_id": client_id}


@router.get("/nonce")
def get_login_nonce(request: Request, response: Response) -> dict[str, str]:
    _require_allowed_origin(request)
    if not settings.google_client_id:
        raise _authentication_not_configured()
    nonce = sessions.create_nonce()
    response.set_cookie(
        key=NONCE_COOKIE,
        value=nonce,
        max_age=NONCE_TTL_SECONDS,
        path=SESSION_COOKIE_PATH,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
    response.headers["Cache-Control"] = "no-store"
    return {"nonce": nonce}


@router.post("/google", status_code=status.HTTP_200_OK)
def google_sign_in(
    body: GoogleSignInRequest,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    _require_allowed_origin(request)
    client_id = settings.google_client_id
    if not client_id:
        raise _authentication_not_configured()
    nonce = request.cookies.get(NONCE_COOKIE)
    if not sessions.consume_nonce(nonce):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign-in attempt expired. Please try again.",
        )

    try:
        claims = verify_google_credential(body.credential, client_id)
        user = _user_from_claims(claims, client_id, nonce or "")
    except GoogleVerifierUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google token verification is unavailable on this server.",
        ) from None
    except InvalidGoogleCredential:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google credential is invalid or expired.",
        ) from None

    session_id, _ = sessions.create(user)
    _set_session_cookie(response, session_id)
    _clear_nonce_cookie(response)
    return {"user": user.model_dump()}


@router.get("/me")
def get_current_user(request: Request, response: Response) -> dict[str, Any]:
    if not settings.google_client_id:
        raise _authentication_not_configured()
    session = _session_for_request(request)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    response.headers["Cache-Control"] = "no-store"
    return {"user": session.user.model_dump()}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    _require_allowed_origin(request)
    sessions.revoke(request.cookies.get(SESSION_COOKIE))
    sessions.consume_nonce(request.cookies.get(NONCE_COOKIE))
    response.delete_cookie(
        key=SESSION_COOKIE,
        path=SESSION_COOKIE_PATH,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
    _clear_nonce_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}
