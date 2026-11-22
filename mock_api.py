#!/usr/bin/env python3
"""Local mock of a paginated, rate-limited REST API.

Used by sync.py --self-test so the demonstration runs with no network access,
no third-party account and no real credentials.

Endpoints
---------
GET /v1/items?cursor=<n>
    Requires: Authorization: Bearer <token>
    200 -> {"items": [...], "next": "<n>" | null}
    429 -> Retry-After: 1   (once per cursor, to exercise backoff)
    401 -> missing or wrong token
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = "demo-token"

ITEMS = {
    "0": [
        {"id": "itm_001", "name": "Insulated Bottle", "price": "24.90", "updated_at": "2026-11-17T08:00:00Z"},
        {"id": "itm_002", "name": "Desk Mat", "price": "39.00", "updated_at": "2026-11-17T08:05:00Z"},
        {"id": "itm_003", "name": "Steel Straws", "price": "9.50", "updated_at": "2026-11-16T19:40:00Z"},
    ],
    "1": [
        {"id": "itm_004", "name": "Notebook A5", "price": "12.00", "updated_at": "2026-11-16T10:00:00Z"},
        {"id": "itm_005", "name": "Desk Lamp", "price": "54.00", "updated_at": "2026-11-15T16:20:00Z"},
    ],
}

NEXT = {"0": "1", "1": None}


class Handler(BaseHTTPRequestHandler):
    rate_limited_once: set[str] = set()

    def log_message(self, fmt: str, *args) -> None:  # keep the demo output readable
        return

    def _send(self, status: int, payload: dict | None, headers: dict | None = None) -> None:
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        if parsed.path != "/v1/items":
            self._send(404, {"error": "not_found"})
            return

        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {TOKEN}":
            self._send(401, {"error": "unauthorized"})
            return

        cursor = (parse_qs(parsed.query).get("cursor") or ["0"])[0]
        if cursor not in ITEMS:
            self._send(400, {"error": "bad_cursor"})
            return

        if cursor not in Handler.rate_limited_once:
            Handler.rate_limited_once.add(cursor)
            self._send(429, {"error": "rate_limited"}, {"Retry-After": "1"})
            return

        self._send(200, {"items": ITEMS[cursor], "next": NEXT[cursor]})


def start(port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    """Start the mock in a background thread and return (server, port)."""
    Handler.rate_limited_once = set()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


if __name__ == "__main__":
    server, port = start(8765)
    print(f"mock API listening on http://127.0.0.1:{port}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
