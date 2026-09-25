"""Single-user authentication, signed sessions and local rate limiting."""

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
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from . import config

COOKIE_NAME = "jev_session"
_PUBLIC_PREFIXES = ("/static/",)
_PUBLIC_PATHS = {"/healthz", "/login", "/logout"}


def auth_password() -> str:
    return os.environ.get("JEV_AUTH_PASSWORD", "")


def auth_enabled() -> bool:
    return bool(auth_password())


def validate_configuration() -> None:
    password = auth_password()
    if password and len(password) < 12:
        raise RuntimeError("JEV_AUTH_PASSWORD doit contenir au moins 12 caractères")
    secret = os.environ.get("JEV_SESSION_SECRET", "")
    if secret and len(secret) < 32:
        raise RuntimeError("JEV_SESSION_SECRET doit contenir au moins 32 caractères")


@lru_cache(maxsize=8)
def _signing_key(password: str, explicit_secret: str) -> bytes:
    material = explicit_secret or password
    return hashlib.pbkdf2_hmac(
        "sha256", material.encode("utf-8"), b"jev-webapp-session-v2.1", 200_000,
    )


def _key() -> bytes:
    password = auth_password()
    if not password:
        return b""
    return _signing_key(password, os.environ.get("JEV_SESSION_SECRET", ""))


def verify_password(candidate: str) -> bool:
    expected = auth_password()
    return bool(expected) and hmac.compare_digest(candidate.encode(), expected.encode())


def create_session() -> str:
    settings = config.settings()["security"]
    payload = {
        "exp": int(time.time()) + int(settings["session_hours"]) * 3600,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=")
    signature = hmac.new(_key(), encoded, hashlib.sha256).digest()
    return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def valid_session(token: str | None) -> bool:
    if not auth_enabled():
        return True
    if not token or "." not in token:
        return False
    encoded_text, signature_text = token.split(".", 1)
    try:
        encoded = encoded_text.encode("ascii")
        padding = "=" * (-len(signature_text) % 4)
        signature = base64.urlsafe_b64decode(signature_text + padding)
        expected = hmac.new(_key(), encoded, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return False
        payload_padding = b"=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + payload_padding))
        return int(payload.get("exp", 0)) >= int(time.time())
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


def safe_next(value: str | None) -> str:
    value = (value or "/").strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


def set_session_cookie(response) -> None:
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


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def client_ip(request: Request) -> str:
    settings = config.settings()["security"]
    if settings["trust_proxy"]:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


class RateLimiter:
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
                    429, "Trop de requêtes. Réessaie plus tard.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)


LIMITER = RateLimiter()


def enforce_rate(request: Request, action: str, limit: int, window_seconds: int) -> None:
    LIMITER.enforce(client_ip(request), action, limit, window_seconds)


class AuthMiddleware(BaseHTTPMiddleware):
    """Default-deny protection for pages and API routes when auth is configured."""

    async def dispatch(self, request: Request, call_next):
        if not auth_enabled():
            return await call_next(request)
        path = request.url.path
        public = path in _PUBLIC_PATHS or any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)
        if not public and not valid_session(request.cookies.get(COOKIE_NAME)):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Authentification requise"}, status_code=401)
            target = quote(path + (f"?{request.url.query}" if request.url.query else ""), safe="/?=&")
            return RedirectResponse(f"/login?next={target}", status_code=303)
        response = await call_next(request)
        if not public:
            response.headers.setdefault("Cache-Control", "no-store")
        return response
