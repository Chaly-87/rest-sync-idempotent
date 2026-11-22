# api-sync-demo

A small, dependency-free Python service that syncs a paginated REST API into SQLite **without duplicating data** — and survives the failures that actually happen in production.

Self-contained demonstration: it runs entirely offline against a local mock API, with no credentials, no third-party packages and no network access.

## What it demonstrates

| Behaviour | Why it matters |
|---|---|
| **Idempotent writes** | Every row carries a SHA-256 fingerprint of its payload. Re-running the same sync reports `unchanged` instead of inserting duplicates. |
| **Cursor pagination with a hard page limit** | Stops and raises instead of looping forever when an API returns a cursor that never ends. |
| **HTTP 429 with `Retry-After`** | Rate limiting is treated as an expected event, not an exception. |
| **Exponential backoff + jitter** | 5xx and transport errors are retried with a delay that grows and is randomised, so several workers do not retry in lockstep. |
| **Explicit failure** | If a page still fails after its retries, the run exits non-zero so a scheduler can alert on it. |
| **Tokens outside the repo** | The bearer token is read from the environment (`API_TOKEN`), never from a file. |
| **Local-only mock** | The mock API binds to `127.0.0.1` and uses a throwaway token, so nothing real is contacted or exposed. |

## Requirements

Python **3.10+** and the standard library only (`urllib`, `sqlite3`, `hashlib`, `json`). No `pip install`.

## Run the demo

```bash
python sync.py --self-test
```

Expected output:

```
first run (cold database)
  retry 1/3 after 2.4s (429 rate limited, retry-after=1)
  page 1 cursor=0 items=3 inserted=3 updated=0
  retry 1/3 after 2.1s (429 rate limited, retry-after=1)
  page 2 cursor=1 items=2 inserted=2 updated=0
second run (same data, proving idempotency)
  page 1 cursor=0 items=3 inserted=0 updated=0
  page 2 cursor=1 items=2 inserted=0 updated=0
first  : {'pages': 2, 'items': 5, 'inserted': 5, 'updated': 0, 'unchanged': 0}
second : {'pages': 2, 'items': 5, 'inserted': 0, 'updated': 0, 'unchanged': 5}
RESULT: PASS
```

The numbers are real output from `python 3.13` on Windows; the wait times vary because jitter is random by design.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

Eight tests, all offline: token rejection, `429` handling, pagination shape, fingerprint stability and sensitivity, two-run idempotency, page-limit enforcement, and the resulting database contents.

## Use it against a real API

```bash
export API_TOKEN="your-token"        # Windows: set API_TOKEN=your-token
python sync.py --config config.example.json
```

Copy `config.example.json` and change `base_url` and `db_path`. The service calls `GET {base_url}/v1/items?cursor=<n>` and expects `{"items": [...], "next": "<cursor>" | null}`, where each item has `id`, `name`, `price` and optionally `updated_at`. Adapt `run_sync` and `SCHEMA` to another payload — the retry, pagination and idempotency mechanics do not change.

## Files

```
sync.py               sync service: retries, pagination, idempotent upserts
mock_api.py           local paginated + rate-limited mock (127.0.0.1 only)
config.example.json   example configuration
tests/test_sync.py    offline test suite
SECURITY.md           what is and is not in this repository
```

## Scope and honest limits

- This is a **demonstration**, not a production library: single process, SQLite, no queue, no migrations, no metrics endpoint.
- It does not handle schema evolution of the upstream API (a renamed field will show up as an `updated` row, not as an error).
- Deleting an item upstream does not delete it locally; soft-delete handling would need a `deleted_at` field on both sides.

## License

MIT — see `LICENSE`.

---

*Demonstration project with fictional data. Not client work.*
