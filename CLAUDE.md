# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python SDET tool that automatically tests HTTP API idempotency — verifying that repeated calls with the same idempotency key produce identical responses and no duplicate DB records. Exposes both a CLI (`idempotency-agent`) and a web UI (`idempotency-web`).

**Read `SKILL.md` before making any changes** — it contains mandatory architecture rules that must be enforced.

Nếu user hỏi về deploy agent lên AgentBase: đọc [`README.md`](greennode-agentbase-skills-main/README.md)

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Test
pytest                  # full suite
pytest -m unit          # unit tests only (fast, no network)

# Lint
ruff check src tests

# CLI
idempotency-agent --url http://localhost:3000/api/orders \
  --body '{"product_id": "abc"}' --key-value key-001 --expected-status 201

# Web UI (http://127.0.0.1:8000)
idempotency-web
```

## Architecture

Strict layered dependency flow — no backwards references allowed:

```
{cli.py, web.py}  →  runner.py  →  {generator, executor, db, validator, reporter, analyzer}  →  {models, config}
```

| Module | Role |
|--------|------|
| `runner.py` | Orchestrates: generate → execute → snapshot → evaluate |
| `generator.py` | Builds test cases and constructs requests with idempotency keys |
| `executor.py` | Async httpx calls — **never raises**, wraps all errors into `APICallResult` |
| `validator.py` | **Pure logic only** (no I/O) — compares responses, checks DB delta, emits `TestResult` |
| `db.py` | MongoDB/MySQL snapshots — errors logged as `[WARN]` and return `None`, never crash the run |
| `analyzer.py` | AI (Claude) interpretation of results — auxiliary only, `validator.py` is the source of truth for PASS/FAIL |
| `planner.py` | AI-driven auto-generation of test configs from curl + description |
| `reporter.py` | HTML (Jinja2 from `templates/`) + terminal summary |
| `models.py` | Pure dataclasses — `TestCase`, `TestResult`, `APICallResult`, `RequestTemplate`, `ScenarioType` |
| `config.py` | Immutable `Settings` dataclass read from env — never hardcode config values |

## Key Design Rules (from SKILL.md)

1. **`validator.py` must be pure** — no network, DB, file I/O, or time calls.
2. **`executor.py` never raises** — all exceptions become `APICallResult.error`.
3. **DB errors don't crash** — `db.py` logs `[WARN]` and returns `None`.
4. **SQL identifiers** — always use `_safe_identifier()`, never f-string user input into SQL.
5. **AI analyzer is auxiliary** — `validator.py`'s PASS/FAIL is truth.
6. **HTML templates separate** — Jinja2 from `templates/`, `autoescape=True`.
7. **Language** — Vietnamese in docs/comments, English for variable/function names.

## Test Scenarios

Scenario types (`ScenarioType` enum): `SINGLE_CALL`, `DUPLICATE_CALL`, `N_CALLS`, `CONCURRENT_CALLS`, `DIFFERENT_KEY`.

Idempotent scenarios (identical response + ≤1 DB record enforced): `DUPLICATE_CALL`, `N_CALLS`, `CONCURRENT_CALLS`.

**Baseline test cases** (9 mandatory, defined in SKILL.md §6): `successful_retry_same_key`, `retry_after_network_timeout`, `key_not_stored_on_timeout`, `concurrent_same_key`, `same_key_different_payload`, `different_key_same_payload`, `key_expiry`, `reuse_key_after_failure`, `missing_idempotency_key`.

When implementing user-specified scenarios, honor exact parameters (e.g., `repeat_count=10` if user says "10 times"), then supplement with baseline cases.

## Configuration

Copy `.env.example` to `.env`:

```
AI_API_KEY=<openrouter/anthropic key>
AI_MODEL=minimax/minimax-m2.5
AI_BASE_URL=<api endpoint>
CONCURRENT_WORKERS=5
N_CALLS=3
REQUEST_TIMEOUT=30
REPORT_OUTPUT_DIR=./reports
```

## Tests Layout

- `tests/unit/` — pure logic, `@pytest.mark.unit`, no network/DB
- `tests/integration/` — async with `respx` mock HTTP, `@pytest.mark.integration`
- `tests/conftest.py` — shared fixtures: `request_template`, `response_template`, `make_call()`, `empty_snapshot`
