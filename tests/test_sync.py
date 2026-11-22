"""Offline tests for the sync demonstration.

Run with:  python -m unittest discover -s tests -v

No network, no credentials, no third-party packages.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mock_api  # noqa: E402
import sync  # noqa: E402


class MockApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server, self.port = mock_api.start(0)
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self) -> None:
        self.server.shutdown()

    def test_wrong_token_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            sync.get_json(f"{self.base}/v1/items?cursor=0", "wrong-token", 5)

    def test_first_request_per_cursor_is_rate_limited(self) -> None:
        with self.assertRaises(sync.RetryableError) as ctx:
            sync.get_json(f"{self.base}/v1/items?cursor=0", "demo-token", 5)
        self.assertIn("429", str(ctx.exception))

    def _get_ignoring_first_429(self, cursor: str) -> dict:
        """The mock rate-limits each cursor once; consume that and return the payload."""
        try:
            sync.get_json(f"{self.base}/v1/items?cursor={cursor}", "demo-token", 5)
        except sync.RetryableError:
            pass
        return sync.get_json(f"{self.base}/v1/items?cursor={cursor}", "demo-token", 5)

    def test_pagination_returns_all_items(self) -> None:
        first = self._get_ignoring_first_429("0")
        self.assertEqual(len(first["items"]), 3)
        self.assertEqual(first["next"], "1")
        second = self._get_ignoring_first_429("1")
        self.assertEqual(len(second["items"]), 2)
        self.assertIsNone(second["next"])


class FingerprintTests(unittest.TestCase):
    def test_same_payload_same_fingerprint(self) -> None:
        item = {"id": "a", "name": "Desk Lamp", "price": "54.00"}
        self.assertEqual(sync.fingerprint(item), sync.fingerprint(dict(item)))

    def test_key_order_does_not_matter(self) -> None:
        self.assertEqual(
            sync.fingerprint({"id": "a", "price": "1.00"}),
            sync.fingerprint({"price": "1.00", "id": "a"}),
        )

    def test_changed_value_changes_fingerprint(self) -> None:
        self.assertNotEqual(
            sync.fingerprint({"id": "a", "price": "1.00"}),
            sync.fingerprint({"id": "a", "price": "2.00"}),
        )


class SyncBehaviourTests(unittest.TestCase):
    def _config(self, db: Path, port: int) -> dict:
        return {
            "base_url": f"http://127.0.0.1:{port}",
            "db_path": str(db),
            "max_retries": 3,
            "timeout_s": 5,
            "max_pages": 10,
            "seed": 1234,
        }

    def test_two_runs_are_idempotent(self) -> None:
        server, port = mock_api.start(0)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "sync.sqlite3"
                cfg = self._config(db, port)
                first = sync.run_sync(cfg, "demo-token")
                second = sync.run_sync(cfg, "demo-token")
        finally:
            server.shutdown()

        self.assertEqual(first, {"pages": 2, "items": 5, "inserted": 5, "updated": 0, "unchanged": 0})
        self.assertEqual(second, {"pages": 2, "items": 5, "inserted": 0, "updated": 0, "unchanged": 5})

    def test_page_limit_is_enforced(self) -> None:
        server, port = mock_api.start(0)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cfg = self._config(Path(tmp) / "sync.sqlite3", port)
                cfg["max_pages"] = 1
                with self.assertRaises(RuntimeError):
                    sync.run_sync(cfg, "demo-token")
        finally:
            server.shutdown()

    def test_database_is_created_and_contains_all_items(self) -> None:
        server, port = mock_api.start(0)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "sync.sqlite3"
                sync.run_sync(self._config(db, port), "demo-token")
                import sqlite3

                conn = sqlite3.connect(db)
                try:
                    rows = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
                    names = [r[0] for r in conn.execute("SELECT name FROM items ORDER BY id")]
                finally:
                    conn.close()
        finally:
            server.shutdown()

        self.assertEqual(rows, 5)
        self.assertEqual(names[0], "Insulated Bottle")


class ConfigTests(unittest.TestCase):
    def test_example_config_is_valid_json(self) -> None:
        cfg = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        self.assertIn("base_url", cfg)
        self.assertIn("db_path", cfg)


if __name__ == "__main__":
    unittest.main()
