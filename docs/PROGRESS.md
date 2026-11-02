# EcoChain Copilot: Project Progress Log

This document tracks progress across all phases, recording what was built, what was measured, and what was deferred.

---

## Phase 0: Recon, Plan, Skeleton

- **Status:** Complete (Gate Passed)
- **What Was Built:**
  - Environment recon completed and recorded (Python 3.12.10, uv 0.12.17).
  - Pinned `requirements.in` created; recompiled `requirements.txt` with `PyJWT`, `argon2-cffi`, `ruff`, `mypy`, `pytest-cov`, and `pre-commit`.
  - Installed all dependencies into `.venv`.
  - Complete repository layout created matching architectural specifications.
  - Configured `pyproject.toml` (ruff, strict mypy for `backend/app`, pytest, coverage).
  - Created `.pre-commit-config.yaml`, `Makefile`, `scripts/check.py`, `.env.example`, `.github/workflows/ci.yml`.
  - Created initial FastAPI app skeleton in `backend/app/main.py` and test in `backend/tests/unit/test_skeleton.py`.
  - Authored `docs/PLAN.md` and `docs/DECISIONS.md`.
- **What Was Measured:**
  - Ruff linter: clean (0 errors).
  - Mypy type checker: clean under strict mode on `backend/app` (0 issues).
  - Pytest: 1 test passed in 0.22s.
- **Deviations / Blockers:**
  - System binaries `tesseract`, `redis-cli`, `psql`, `ollama` are not available directly on the Windows host path. Recorded in `docs/PLAN.md`; interface fakes/mocks will be used for unit tests, with Docker Compose providing the containerized environment for integration.
- **Next Phase:** Phase 1: Foundations (Config, domain models, DB schema, tamper-evident audit log).

---

## Phase 1: Foundations

- **Status:** Complete (Gate Passed)
- **What Was Built:**
  - `core/config.py`: `pydantic-settings` configuration supporting dynamic model selection via `GEMINI_MODEL`, risk/verification thresholds, database and security settings.
  - `core/logging.py`: Structured JSON logging with `PIISafeFilter` (redacts emails, IBANs, phone numbers, cards) and contextual correlation (`job_id`, `thread_id`, `tenant_id`).
  - `core/errors.py`: Standard domain exception hierarchy with typed error codes (`EcoChainError`, `ValidationError`, `PrivacyViolationError`, `AuditChainTamperError`, `TenantIsolationError`).
  - `domain/models.py`: Complete domain contracts: `BBox` (normalized 0-1000 with validation), `ExtractedField`, `EvidenceItem`, `Claim` (strictly requiring evidence IDs), `Verdict`, `RiskForecast`, `DocumentRef`, `RedactedPage`, `EscalationState`, `ScorecardLine`, `Scorecard`, and `GraphState` with append-only reducers.
  - `db/models.py`: SQLAlchemy ORM models for `tenants`, `users`, `factories`, `documents`, `jobs`, `reviews`, and `audit_events`. DB-level append-only enforcement via event listeners preventing `UPDATE` and `DELETE` on `audit_events`.
  - `db/audit_log.py`: Append-only cryptographic audit logger with SHA-256 hash chaining (`prev_hash`, `event_hash`) and full chain verification via `verify_chain()`.
  - `alembic.ini` and initial migration `2026_11_02_0001_initial_schema.py`: tested clean upgrade, rollback (downgrade), and re-upgrade.
- **What Was Measured:**
  - Ruff linter: green (0 errors).
  - Mypy type checker: green under strict mode on `backend/app` (0 issues across 26 source files).
  - Pytest: 11 unit tests passed in 0.86s (contracts, validation, PII redaction, append-only enforcement, raw SQL tamper detection).
- **Deviations / Blockers:**
  - None. In-memory SQLite fixture provides fast unit test coverage while Alembic migrations support PostgreSQL in staging/production.
- **Next Phase:** Phase 2: Data (Synthetic and Real).
