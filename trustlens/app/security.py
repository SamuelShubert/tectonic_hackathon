"""HTTP-level security controls.

- SecurityHeadersMiddleware: browser hardening on every response.
  The CSP forbids inline scripts, so the frontend must load its JS from
  /static/app.js (not an inline <script> block). This neutralises most XSS
  even if someone accidentally uses innerHTML.
- BodySizeLimitMiddleware: rejects oversized request bodies before they
  are read, so nobody can make the server buffer megabytes of JSON.
- RateLimiter: a per-client sliding window. It protects the LLM credits:
  every request costs money, so unlimited requests are a cost-exhaustion
  attack (a business-logic flaw, not just a performance issue).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque

from starlette.types import ASGIApp, Receive, Scope, Send

SECURITY_HEADERS = {
    b"content-security-policy": (
        b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        b"img-src 'self' data:; object-src 'none'; base-uri 'none'; "
        b"frame-ancestors 'none'; form-action 'self'"
    ),
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
    b"cache-control": b"no-store",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])
                           if k.lower() not in SECURITY_HEADERS and k.lower() != b"server"]
                headers.extend(SECURITY_HEADERS.items())
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length is None or not length.isdigit():
            await _reject(send, 411, b'{"detail":"Content-Length required"}')
            return
        if int(length) > self.max_bytes:
            await _reject(send, 413, b'{"detail":"Request too large"}')
            return

        # Also enforce while streaming, in case the header lies.
        received = 0

        async def limited_receive() -> dict:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise ValueError("Body exceeded declared limit")
            return message

        await self.app(scope, limited_receive, send)


async def _reject(send: Send, status: int, body: bytes) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class RateLimiter:
    """Thread-safe sliding window: at most `limit` requests per `window` seconds per key."""

    MAX_TRACKED_KEYS = 10_000  # bounds memory even under many spoofed clients

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.pop(key, None) or deque()
            while hits and now - hits[0] > self.window:
                hits.popleft()
            allowed = len(hits) < self.limit
            if allowed:
                hits.append(now)
            self._hits[key] = hits  # re-insert as most recently used
            while len(self._hits) > self.MAX_TRACKED_KEYS:
                self._hits.popitem(last=False)
            return allowed
