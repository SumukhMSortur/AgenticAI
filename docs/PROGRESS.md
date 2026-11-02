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

---

## Phase 2: Data (Synthetic and Real)

- **Status:** Complete (Gate Passed)
- **What Was Built:**
  - `scripts/generate_issuer_registry.py`: Approved mock certificate issuer registry (`data/registry/approved_issuers.csv`) covering Control Union, Ecocert, OEKO-TEX, SGS, Intertek, Bureau Veritas, and TÜV Rheinland.
  - `scripts/generate_regulations.py`: Versioned legal texts in `data/regulations/csddd_regulations.json`, including the superseded Directive (EU) 2024/1760 and the in-force Omnibus I Directive (EU) 2026/470 and ESPR (EU) 2024/1781.
  - `scripts/generate_audit_histories.py`: 450 factories generated with 36-month time series of numeric signals (`carbon_intensity`, `labor_violations`, `cert_lapse_days`, `corrective_action_backlog`, `safety_incidents`). Grounded in a latent hazard process with drift and seasonality. Stratified 70/15/15 train/val/test split by factory.
  - `scripts/generate_documents.py`: 180 synthetic PDFs generated with PyMuPDF (120 clean, 60 adversarial spanning expired validity, unapproved/fuzzy issuers, and scope/facility mismatches), with normalized bounding boxes (0-1000) and embedded privacy seeds (`PERSON`, `EMAIL_ADDRESS`, `IBAN_CODE`, `PRICE`).
  - `scripts/generate_golden_set.py`: 150 labeled end-to-end evaluation cases in `data/golden/golden_set.json` with expected verdicts and escalation flags.
  - `scripts/generate_synthetic_data.py`: Master generation entrypoint and SHA-256 integrity validator outputting `data/MANIFEST.json`.
- **What Was Measured:**
  - `data/MANIFEST.json`: 7 files cryptographically hashed and verified byte-identical.
  - Total test suite: 16 unit tests passing in 2.29s.
  - Ruff linter & Mypy strict: green across all modules.
- **Deviations / Blockers:**
  - PDF binary outputs are gitignored to preserve repo compactness; generation is 100% deterministic from `SEED=42` and reproducible via `make data`.
- **Next Phase:** Phase 3: Privacy Boundary (OCR, Presidio + regex redaction, Llama checker, Vault, OutboundGuard, Leakage suite).

---

## Phase 3: Privacy Boundary

- **Status:** Complete (Gate Passed)
- **What Was Built:**
  - `config/recognizers.yaml`: Presidio and regex recognizer specifications for prices, IBANs, phone numbers, supplier IDs, and facility IDs.
  - `privacy/ocr.py`: `IOcrEngine` interface with `PyMuPdfOcrEngine` local text and word bounding box extraction normalized to the 0-1000 LayoutLM space.
  - `privacy/vault.py`: `TokenVault` providing per-tenant reversible AES-256 Fernet tokenization (`[PERSON_001]`, `[IBAN_CODE_001]`, etc.), deterministic detokenization, rehydration, and sensitive entity tracking.
  - `privacy/redactor.py`: `DocumentRedactor` combining Presidio `AnalyzerEngine`, custom regex recognizers, template stopword filtering, and bbox preservation into `RedactedPage`.
  - `privacy/llama_checker.py`: Second-pass local sensitive data inspector using Ollama with fail-closed behavior (`FakeLlamaChecker` for tests).
  - `privacy/outbound_guard.py`: Single choke-point for all cloud LLM requests enforcing image byte elimination, 500k char size limits, zero vault-known value leakage, and outbound payload hashing to the audit log.
  - `tests/leakage/test_privacy_leakage.py`: Leakage test suite across 180 documents (720 privacy seeds) and code AST inspection asserting zero direct LLM imports outside `backend/app/llm/`.
- **What Was Measured:**
  - `reports/redaction.json`: 720/720 seeded PII items detected (100% recall across `PERSON`, `EMAIL_ADDRESS`, `IBAN_CODE`, `PRICE`).
  - Total leakage rate: 0.0% (zero seeded values leaked into outbound payloads).
  - Total test suite: 22 unit & leakage tests passing in 16.4s.
  - Ruff linter & Mypy strict: green across 31 source files.
- **Deviations / Blockers:**
  - Template label words (`facility`, `supplier`, etc.) are filtered from entity tokenization to prevent template headers from colliding with sensitive entity checks.
- **Next Phase:** Phase 4: Extraction (Base interface, LayoutLMv3, Heuristic extractor, normalizers, evaluation script).
