"""Outbound HTTP helpers with SSRF protection and redirect revalidation."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit


class UnsafeUrl(ValueError):
    pass


@dataclass(frozen=True)
class SafeTarget:
    url: str
    scheme: str
    host: str
    port: int
    path: str
    addresses: tuple[str, ...]


def _allowed_address(raw: str) -> bool:
    address = ipaddress.ip_address(raw.split("%", 1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return bool(address.is_global)


def validate_url(url: str) -> SafeTarget:
    raw = (url or "").strip()
    if not raw or any(char in raw for char in ("\x00", "\r", "\n", "\t", "\\")):
        raise UnsafeUrl("URL invalide")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrl("URL invalide") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeUrl("Seules les URL HTTP et HTTPS sont autorisées")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrl("Les identifiants intégrés dans une URL sont interdits")
    if not parsed.hostname:
        raise UnsafeUrl("Nom d’hôte absent")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeUrl("Destination locale interdite")
    port = port or (443 if parsed.scheme.lower() == "https" else 80)
    if port not in (80, 443):
        raise UnsafeUrl("Seuls les ports HTTP 80 et HTTPS 443 sont autorisés")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrl("Nom d’hôte introuvable") from exc
    addresses = tuple(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses or any(not _allowed_address(address) for address in addresses):
        raise UnsafeUrl("Destination privée, locale ou réservée interdite")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    canonical = urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))
    return SafeTarget(canonical, parsed.scheme.lower(), host, port, path, addresses)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, target: SafeTarget, address: str, timeout: float):
        super().__init__(target.host, target.port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, target: SafeTarget, address: str, timeout: float):
        self._ssl_context = ssl.create_default_context()
        super().__init__(target.host, target.port, timeout=timeout, context=self._ssl_context)
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)


def _request_once(target: SafeTarget, headers: dict[str, str], timeout: float,
                  max_bytes: int) -> tuple[int, dict[str, str], bytes]:
    last_error: Exception | None = None
    for address in target.addresses:
        connection_cls = _PinnedHTTPSConnection if target.scheme == "https" else _PinnedHTTPConnection
        connection = connection_cls(target, address, timeout)
        try:
            host_header = target.host
            if (target.scheme, target.port) not in (("http", 80), ("https", 443)):
                host_header = f"{host_header}:{target.port}"
            connection.request("GET", target.path, headers={"Host": host_header, **headers})
            response = connection.getresponse()
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise UnsafeUrl("Réponse distante trop volumineuse")
            return response.status, {key.lower(): value for key, value in response.getheaders()}, body
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            connection.close()
    raise UnsafeUrl(f"Connexion distante impossible : {last_error}")


def fetch_bytes(url: str, *, headers: dict[str, str] | None = None, timeout: float = 30,
                max_bytes: int = 5_000_000, max_redirects: int = 5) -> tuple[bytes, dict[str, str], str]:
    current = url
    request_headers = headers or {}
    for redirect_count in range(max_redirects + 1):
        target = validate_url(current)
        status, response_headers, body = _request_once(target, request_headers, timeout, max_bytes)
        if status in {301, 302, 303, 307, 308}:
            location = response_headers.get("location")
            if not location:
                raise UnsafeUrl("Redirection sans destination")
            if redirect_count >= max_redirects:
                raise UnsafeUrl("Trop de redirections")
            next_url = urljoin(target.url, location)
            next_target = validate_url(next_url)
            if target.scheme == "https" and next_target.scheme != "https":
                raise UnsafeUrl("Redirection HTTPS vers HTTP interdite")
            current = next_target.url
            continue
        if status < 200 or status >= 400:
            raise UnsafeUrl(f"Réponse HTTP {status}")
        return body, response_headers, target.url
    raise UnsafeUrl("Trop de redirections")


def fetch_text(url: str, *, headers: dict[str, str] | None = None, timeout: float = 30,
               max_bytes: int = 5_000_000) -> str:
    body, response_headers, _ = fetch_bytes(
        url, headers=headers, timeout=timeout, max_bytes=max_bytes,
    )
    content_type = response_headers.get("content-type", "")
    charset = "utf-8"
    for part in content_type.split(";")[1:]:
        if "charset=" in part.lower():
            charset = part.split("=", 1)[1].strip().strip('"') or "utf-8"
            break
    return body.decode(charset, "replace")
