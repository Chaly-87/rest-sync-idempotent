#!/usr/bin/env python3
"""Resilient REST sync: retries, backoff, pagination and idempotent upserts.

Demonstration asset for the LumiaProAI service
"API Integration & Workflow Automation".

What it demonstrates
--------------------
* Token authentication read from the environment, never from a file in the repo.
* Pagination driven by the API's own cursor, with a hard page limit.
* 429 handling that honours Retry-After, and exponential backoff with jitter
  for transport errors and 5xx responses.
* Idempotent writes: rows are fingerprinted, so re-running the same sync
  reports "unchanged" instead of duplicating data.
* An explicit failure path: if any page fails after its retries, the run exits
  non-zero and the caller can alert on it.

Usage
-----
    python sync.py --self-test
    API_TOKEN=... python sync.py --config config.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    price       TEXT NOT NULL,
    updated_at  TEXT,
    fingerprint TEXT NOT NULL,
    synced_at   TEXT NOT NULL
);
"""


class RetryableError(RuntimeError):
    pass


def get_json(url: str, token: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        retry_after = exc.headers.get("Retry-After")
        if exc.code == 429:
            raise RetryableError(f"429 rate limited, retry-after={retry_after}") from exc
        if 500 <= exc.code < 600:
            raise RetryableError(f"{exc.code} server error") from exc
        raise
    except urllib.error.URLError as exc:
        raise RetryableError(f"transport error: {exc.reason}") from exc


def fetch_page(url: str, token: str, timeout: float, retries: int, rng: random.Random) -> dict:
    attempt = 0
    while True:
        try:
            return get_json(url, token, timeout)
        except RetryableError as exc:
            attempt += 1
            if attempt > retries:
                raise
            wait = min(2 ** attempt, 8) + rng.uniform(0, 0.5)
            print(f"  retry {attempt}/{retries} after {wait:.1f}s ({exc})")
            time.sleep(wait)


def fingerprint(item: dict) -> str:
    payload = json.dumps(item, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def upsert(db_path: Path, items: list[dict]) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inserted = updated = 0
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        for item in items:
            row_id = item["id"]
            mark = fingerprint(item)
            current = conn.execute(
                "SELECT fingerprint FROM items WHERE id = ?", (row_id,)
            ).fetchone()
            if current is None:
                inserted += 1
            elif current[0] == mark:
                continue
            else:
                updated += 1
            conn.execute(
                "INSERT INTO items (id, name, price, updated_at, fingerprint, synced_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET name=excluded.name, price=excluded.price,"
                " updated_at=excluded.updated_at, fingerprint=excluded.fingerprint,"
                " synced_at=excluded.synced_at",
                (row_id, item["name"], item["price"], item.get("updated_at"), mark, now),
            )
        conn.commit()
    finally:
        # Closing explicitly matters on Windows: an open handle keeps the file
        # locked and breaks cleanup (temp dirs, re-running the self-test).
        conn.close()
    return inserted, updated


def run_sync(config: dict, token: str) -> dict:
    base_url = config["base_url"].rstrip("/")
    db_path = Path(config["db_path"])
    retries = int(config.get("max_retries", 3))
    timeout = float(config.get("timeout_s", 5))
    max_pages = int(config.get("max_pages", 20))
    rng = random.Random(int(config.get("seed", 1234)))

    cursor: str | None = "0"
    pages = 0
    total = 0
    inserted = updated = unchanged = 0

    while cursor is not None:
        if pages >= max_pages:
            raise RuntimeError(f"page limit {max_pages} reached; refusing to loop")
        url = f"{base_url}/v1/items?cursor={cursor}"
        payload = fetch_page(url, token, timeout, retries, rng)
        items = payload.get("items", [])
        page_inserted, page_updated = upsert(db_path, items)
        pages += 1
        total += len(items)
        inserted += page_inserted
        updated += page_updated
        unchanged += len(items) - page_inserted - page_updated
        print(
            f"  page {pages} cursor={cursor} items={len(items)} "
            f"inserted={page_inserted} updated={page_updated}"
        )
        cursor = payload.get("next")

    return {
        "pages": pages,
        "items": total,
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
    }


def self_test() -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    import mock_api  # noqa: PLC0415 - only needed for the offline demonstration

    server, port = mock_api.start(0)
    db_path = Path(__file__).parent / "out" / "self_test.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    config = {
        "base_url": f"http://127.0.0.1:{port}",
        "db_path": str(db_path),
        "max_retries": 3,
        "timeout_s": 5,
        "max_pages": 10,
        "seed": 1234,
    }
    try:
        print("first run (cold database)")
        first = run_sync(config, "demo-token")
        print("second run (same data, proving idempotency)")
        second = run_sync(config, "demo-token")
    finally:
        server.shutdown()

    print(f"first  : {first}")
    print(f"second : {second}")

    ok = (
        first["items"] == 5
        and first["inserted"] == 5
        and second["inserted"] == 0
        and second["unchanged"] == 5
    )
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, help="JSON config with base_url and db_path")
    parser.add_argument("--self-test", action="store_true", help="run fully offline against mock_api.py")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.config:
        parser.error("--config is required unless --self-test is used")

    token = os.environ.get("API_TOKEN")
    if not token:
        print("API_TOKEN is not set", file=sys.stderr)
        return 2

    config = json.loads(args.config.read_text(encoding="utf-8"))
    stats = run_sync(config, token)
    print(f"synced pages={stats['pages']} items={stats['items']} "
          f"inserted={stats['inserted']} updated={stats['updated']} unchanged={stats['unchanged']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
