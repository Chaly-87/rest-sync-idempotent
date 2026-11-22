# Security notes

## What this repository contains

Three code files, one example configuration, one test file and documentation. Everything is original work by the author, written for this demonstration. There are no third-party dependencies: the code imports only the Python standard library (`urllib`, `sqlite3`, `hashlib`, `json`, `argparse`, `random`, `time`, `threading`, `http.server`).

## What it deliberately does not contain

- **No credentials.** No API keys, tokens, passwords, cookies or session IDs. The mock uses the literal string `demo-token`, which is checked by the mock itself and is not valid anywhere else.
- **No real endpoints.** The only hostnames are `127.0.0.1` (the local mock) and the placeholder `api.example.com` in the example config.
- **No personal data.** The mock dataset is five fictional products with prices.
- **No internal systems.** No reference to, or code from, any private infrastructure, internal tooling or employer system.
- **No build artefacts.** The SQLite database produced by a run lands in `out/`, which is git-ignored.

## Execution safety

- The mock server binds to `127.0.0.1` only and is started on an ephemeral port (`port=0`) during tests, so it is not reachable from the network.
- No `shell=True`, no `subprocess`, no `eval`, no dynamic import of untrusted paths.
- Database writes go to the path given in the config; tests use a temporary directory.
- The demonstration run makes no outbound network requests at all.

## Reporting

If you find a security problem in this code, open an issue describing the behaviour and the steps to reproduce it. Please do not include real credentials or personal data in the report.
