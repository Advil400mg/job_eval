"""Multi-user authentication v2.3 — HMAC-signed sessions, AuthMiddleware, CSRF protection.

Sessions carry user_id + session_version + expiration, signed with HMAC-SHA256.
Backward-compatible: legacy single-user (JEV_AUTH_PASSWORD) still works via
verify_password() / set_session_cookie().  Multi-user mode uses the users table
via app.accounts and validates session_version for forced-logout support.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import lru_cache
from urllib.parse import quote, urlsplit

from fastapi import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN, HTTP_429_TOO_MANY_REQUESTS

from . import accounts, config

COOKIE_NAME = "jev_session"
_PUBLIC_PREFIXES = ("/static/",)
_PUBLIC_PATHS = frozenset({"/healthz", "/login", "/setup-admin", "/register"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_EPHEMERAL_SECRET = secrets.token_urlsafe(48)


# ── Helpers ──────────────────────────────────────────────────────────

def auth_password() -> str:
    return os.environ.get("JEV_AUTH_PASSWORD", "")


def auth_enabled() -> bool:
    """v2.3 always protects application data; setup routes remain public."""
    return True


def _multi_user_mode() -> bool:
    """True when no legacy JEV_AUTH_PASSWORD is set (pure multi-user)."""
    return not bool(auth_password())


def validate_configuration() -> None:
    password = auth_password()
    if password and len(password) < 12:
        raise RuntimeError("JEV_AUTH_PASSWORD doit contenir au moins 12 caractères")
    secret = os.environ.get("JEV_SESSION_SECRET", "")
    if password and secret and len(secret) < 32:
        raise RuntimeError("JEV_SESSION_SECRET doit contenir au moins 32 caractères")
    if _multi_user_mode() and secret and len(secret) < 32:
        raise RuntimeError("JEV_SESSION_SECRET doit contenir au moins 32 caractères")


# ── Signing key ──────────────────────────────────────────────────────

@lru_cache(maxsize=8)
def _signing_key(password: str, explicit_secret: str) -> bytes:
    material = explicit_secret or password
    if not material:
        return b""
    return hashlib.pbkdf2_hmac(
        "sha256",
        material.encode("utf-8"),
        b"jev-webapp-session-v2.3",
        200_000,
    )


def _key() -> bytes:
    password = auth_password()
    secret = os.environ.get("JEV_SESSION_SECRET", "")
    return _signing_key(password, secret or _EPHEMERAL_SECRET)


# ── Legacy single-user helpers ───────────────────────────────────────

def verify_password(candidate: str) -> bool:
    """Constant-time comparison against JEV_AUTH_PASSWORD (single-user mode)."""
    expected = auth_password()
    return bool(expected) and hmac.compare_digest(candidate.encode(), expected.encode())


# ── Session token helpers ────────────────────────────────────────────

def _make_token(payload: dict) -> str:
    """Encode and sign *payload* with the HMAC key."""
    key = _key()
    if not key:
        return ""
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    ).rstrip(b"=")
    signature = hmac.new(key, encoded, hashlib.sha256).digest()
    return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _parse_token(token: str | None) -> dict | None:
    """Verify HMAC signature and return the decoded payload, or None."""
    if not token or "." not in token:
        return None
    key = _key()
    if not key:
        return None
    encoded_text, signature_text = token.split(".", 1)
    try:
        encoded = encoded_text.encode("ascii")
        expected = hmac.new(key, encoded, hashlib.sha256).digest()
        sig_padding = b"=" * (-len(signature_text) % 4)
        signature = base64.urlsafe_b64decode(
            signature_text.encode("ascii") + sig_padding,
        )
        if not hmac.compare_digest(signature, expected):
            return None
        payload_padding = b"=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + payload_padding))
        if int(payload.get("e", 0)) < int(time.time()):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def create_session() -> str:
    """Create a legacy single-user session (no user identity)."""
    settings = config.settings()["security"]
    payload = {
        "e": int(time.time()) + int(settings["session_hours"]) * 3600,
        "n": secrets.token_urlsafe(12),
    }
    return _make_token(payload)


def create_user_session(user_id: str, session_version: int) -> str:
    """Create a multi-user session carrying user_id + session_version."""
    settings = config.settings()["security"]
    payload = {
        "u": user_id,
        "v": session_version,
        "e": int(time.time()) + int(settings["session_hours"]) * 3600,
        "n": secrets.token_urlsafe(12),
    }
    return _make_token(payload)


def valid_session(token: str | None) -> bool:
    """Check whether *token* is a valid session (legacy or multi-user).

    For legacy sessions (no ``u`` key) the legacy password must be set.
    For multi-user sessions the referenced user must exist and the stored
    ``session_version`` must match.
    """
    payload = _parse_token(token)
    if payload is None:
        return False
    # Legacy session (no user key)
    if "u" not in payload:
        return bool(auth_password())
    # Multi-user session
    user = accounts.get_user(payload["u"])
    if not user:
        return False
    return user.get("session_version", 0) == payload.get("v")


def load_session(token: str | None) -> dict | None:
    """Return the logged-in user dict, or None if the token is invalid.

    In legacy single-user mode a virtual admin dict is returned when the
    token is valid.
    """
    payload = _parse_token(token)
    if payload is None:
        return None
    # Legacy session → virtual admin (only when legacy password is set)
    if "u" not in payload:
        if not auth_password():
            return None
        return {"id": "legacy-admin", "role": "admin", "username": "admin"}
    # Multi-user session → real user from DB
    user = accounts.get_user(payload["u"])
    if not user:
        return None
    if user.get("session_version", 0) != payload.get("v"):
        return None
    return user


# ── Cookie helpers ───────────────────────────────────────────────────

def set_session_cookie(response) -> None:
    """Set ``jev_session`` cookie (legacy single-user mode)."""
    settings = config.settings()["security"]
    response.set_cookie(
        COOKIE_NAME,
        create_session(),
        max_age=int(settings["session_hours"]) * 3600,
        httponly=True,
        secure=bool(settings["cookie_secure"]),
        samesite="strict",
        path="/",
    )


def set_user_session_cookie(response, user_id: str, session_version: int) -> None:
    """Set ``jev_session`` cookie for a multi-user session."""
    settings = config.settings()["security"]
    response.set_cookie(
        COOKIE_NAME,
        create_user_session(user_id, session_version),
        max_age=int(settings["session_hours"]) * 3600,
        httponly=True,
        secure=bool(settings["cookie_secure"]),
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


# ── Safe redirect helper ─────────────────────────────────────────────

def safe_next(value: str | None) -> str:
    """Return a safe relative URL, falling back to ``/`` for external/unsafe."""
    value = (value or "/").strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


# ── Rate limiter ─────────────────────────────────────────────────────

class RateLimiter:
    """Per-(client, action) sliding-window rate limiter."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def enforce(self, key: str, action: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        bucket_key = (key, action)
        with self._lock:
            bucket = self._events[bucket_key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                raise HTTPException(
                    HTTP_429_TOO_MANY_REQUESTS,
                    "Trop de requêtes. Réessaie plus tard.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)


LIMITER = RateLimiter()


def enforce_rate(request: Request, action: str, limit: int, window_seconds: int) -> None:
    """Convenience wrapper around ``LIMITER.enforce`` that extracts the client IP."""
    LIMITER.enforce(client_ip(request), action, limit, window_seconds)


# ── Client IP ────────────────────────────────────────────────────────

def client_ip(request: Request) -> str:
    settings = config.settings()["security"]
    if settings["trust_proxy"]:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


# ── CSRF check ───────────────────────────────────────────────────────

def _is_same_origin(request: Request) -> bool:
    """Return True if Origin / Referer matches the request's own origin.

    Strict check: on authenticated mutations at least one of the two
    headers must be present and match the server's own origin.  When
    neither is present the request is rejected.
    """
    host = request.url.hostname or ""
    port = request.url.port
    scheme = request.url.scheme
    origin_str = f"{scheme}://{host}"
    if port and port not in (80, 443):
        origin_str += f":{port}"

    origin = request.headers.get("origin")
    if origin:
        return origin == origin_str

    referer = request.headers.get("referer")
    if referer:
        try:
            parsed = urlsplit(referer)
            actual_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            return False
        expected_port = port or (443 if scheme == "https" else 80)
        return (
            parsed.scheme == scheme
            and (parsed.hostname or "") == host
            and actual_port == expected_port
        )

    return False


class ResponseHeadersMiddleware(BaseHTTPMiddleware):
    """Apply browser security headers to public and authenticated responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response


# ── Auth middleware ──────────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    """Protect routes behind authentication and set ``request.state.user``.

    **request.state.user** is a dict (the user row from ``accounts.get_user``)
    or ``None`` for anonymous requests.

    Public routes (``/healthz``, ``/login``, ``/setup-admin``, ``/register``,
    ``/static/...``) are always accessible.

    Protected routes return 401 (JSON) or redirect to ``/login`` (HTML) when
    the session is missing or expired.

    State-changing methods (POST, PUT, PATCH, DELETE) on protected routes
    with a valid session are additionally CSRF-protected via Origin/Referer
    checking.

    Legacy single-user mode is fully supported: ``verify_password`` and
    ``set_session_cookie`` still work; the middleware returns a virtual
    admin dict as ``request.state.user``.
    """

    async def dispatch(self, request: Request, call_next):  # noqa: C901
        path = request.url.path
        public = path in _PUBLIC_PATHS or any(
            path.startswith(prefix) for prefix in _PUBLIC_PREFIXES
        )

        if accounts.active_user_count() == 0:
            request.state.user = None
            if public:
                return await call_next(request)
            if path.startswith("/api/"):
                return JSONResponse(
                    {"detail": "Création du premier administrateur requise"}, status_code=428,
                )
            return RedirectResponse("/setup-admin", status_code=303)

        user = load_session(request.cookies.get(COOKIE_NAME))
        request.state.user = user

        # Public routes are always accessible
        if public:
            return await call_next(request)

        # Protected routes require a valid session
        if user is None:
            if path.startswith("/api/"):
                return JSONResponse(
                    {"detail": "Authentification requise"},
                    status_code=HTTP_401_UNAUTHORIZED,
                )
            target = quote(
                path + (f"?{request.url.query}" if request.url.query else ""),
                safe="/?=&",
            )
            return RedirectResponse(f"/login?next={target}", status_code=303)

        # Logout relies on the Strict SameSite session cookie and must remain usable
        # behind proxies that do not preserve Origin/Referer correctly.
        csrf_exempt = request.method == "POST" and path == "/logout"
        if request.method not in _SAFE_METHODS and not csrf_exempt and not _is_same_origin(request):
            return JSONResponse(
                {"detail": "Requête interdite (origine non vérifiée)"},
                status_code=HTTP_403_FORBIDDEN,
            )

        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        return response