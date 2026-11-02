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

---

## Recovery checkpoint and Phase 6 (2026-11-02)

- **Recovery verified:** Repository is on `main`, seven commits ahead of `origin/main`, with tags through `phase-5-complete` and `addendum-a-complete`. The master prompt and live-data addendum referenced by the resume prompt are not present in the checkout, so their detailed rule tables and acceptance criteria remain unverified.
- **Gate from the repository root:** Ruff passed; strict mypy passed with no issues across 52 source files; pytest passed (50 passed). The implemented verifier package has 100% statement coverage (158/158 statements); total application coverage is 92%.
- **Phase 6 status:** Partial. Nine rule functions (V-EXP-001/002, V-DATE-001, V-ISS-001/002, V-SCOPE-001/002, V-XDOC-001/002) now produce the canonical evidence-linked `Verdict`; their boundary tests pass with 100% statement coverage. The mock issuer registry loader is implemented and emits a visible `MOCK` warning.
- **Known Phase 6 gaps:** No verifier engine, V-PAGE-001, V-CONF-001, V-EXT-001/002/003/900, V-SANC-001/002, provider interface/fakes, golden-set report, or `reports/verifier.json` yet. The eight missing rules depend on specifications absent from this checkout.
- **Contract decision:** ADR-008 records the canonical verdict shape and V-DATE-001 escalation behavior.
- **Windows services checked:** Python 3.12.10, Node, and npm are available. Tesseract, Ollama, Redis CLI, PostgreSQL CLI, and Docker are not available on PATH; service-backed integration checks remain blocked.
- **Next action:** Restore `ECOCHAIN_MASTER_PROMPT.md` and `ECOCHAIN_ADDENDUM_LIVE_DATA.md`, then implement and test the remaining verifier rules against those specifications.

## Phase 6 implementation checkpoint (2026-11-02)

- **Status:** Implementation and gates pass; Phase 6 remains partial until the report is regenerated after the implementation commit.
- **What Was Built:** Added the remaining page-count, confidence, external snapshot, provider-outage, and sanctions rules; deterministic `Verifier` orchestration; validated `config/verifier.yaml` thresholds; snapshot/provider contracts and deterministic fakes; critical/normal escalation priority; and a seeded golden evaluator. Corrected the golden fixture's page-count field and fuzzy issuer example.
- **What Was Measured:** Python 3.12.10; Ruff clean; strict mypy clean across 64 source files; 63 tests passed; verifier package coverage 397/397 statements (100%). The synthetic golden evaluator matched 150/150 expected rule verdicts and 150/150 escalation outcomes. The seeded data manifest verifies.
- **Deviations / Blockers:** `ECOCHAIN_ADDENDUM_LIVE_DATA.md` is absent, so the external/sanctions behavior and priority details are conservative assumptions recorded in ADR-009, not verified Addendum A3 requirements. The golden set has no expected V-EXT/V-SANC labels. The generated report must be rerun after the implementation commit so its Git provenance identifies the code it measures.
- **Next Phase:** Finish the Phase 6 report/provenance commit and tag before assessing Phase 7's locked training dependencies.

## Phase 6: Deterministic verifier (complete, 2026-11-02)

- **Status:** Complete; implementation commit `0a64e25`. The phase tag is applied to the report/progress checkpoint commit.
- **What Was Built:** All 17 verifier rules are orchestrated in deterministic order over evidence-linked claims and vault-mapped context. Added the missing eight rules, validated YAML thresholds, local snapshot provider contracts/fakes, and explicit `normal`/`critical` escalation priority. Added seeded golden evaluation and corrected the page-count fixture key.
- **What Was Measured:** Ruff clean; strict mypy clean across 64 source files; 63 tests passed; all 397 statements in `backend/app/verifier/` covered (100%). `reports/verifier.json` records 150/150 expected verdicts and 150/150 expected escalation outcomes, dataset SHA-256 `b03022a6d195729e038ba07f311ebc3b846c33125b8943cb75610af86b5a78a3`, seed 42, and source commit `0a64e25`. `data/MANIFEST.json` verifies.
- **Deviations / Blockers:** The attached master prompt was used as the Phase 6 rule source. `ECOCHAIN_ADDENDUM_LIVE_DATA.md` was not present, so external/sanctions behavior remains the conservative, explicitly unverified assumption documented in ADR-009. The synthetic golden set has no expected V-EXT/V-SANC labels; its 100% figure measures only the labels it contains.
- **Next Phase:** Phase 7: verify the locked ML stack, then implement reproducible CPU baselines/LSTM, validation-only calibration, and promotion logic.

## Phase 7 implementation checkpoint (2026-11-02)

- **Status:** Implementation and gates pass; Phase 7 remains partial until the report is regenerated after the implementation commit.
- **What Was Built:** Added train-window-only sequence and summary features; factory-disjoint data loading; train-only normalizers; Logistic Regression and XGBoost baselines; a seeded CPU LSTM with validation early stopping; validation-only Platt calibration; bootstrap test confidence intervals; reliability curves/ECE; config-driven promotion; hash-verified inference; and `make train` risk wiring. The generated joblib artifact remains ignored and local.
- **What Was Measured:** Python 3.12.10 with locked scikit-learn 1.9.1, XGBoost 3.4.1, and CPU PyTorch 2.15.0. Ruff and strict mypy passed; 70 tests passed; the risk package has 167/167 statements covered (100%). CPU training took 10.5 seconds. All three models scored AUROC 1.000 on the synthetic test split; XGBoost scored PR-AUC 1.000, Brier 0.000229, and ECE 0.006947. The LSTM did not meet the configured AUROC margin against both baselines, so XGBoost was selected using validation metrics. Repeated training reproduced model metrics and the artifact hash.
- **Deviations / Blockers:** Scores are synthetic-only and unusually strong because of the generated signal process; they do not represent real-world performance. The artifact is intentionally not committed; the training command recreates it. The report's Git provenance will be refreshed after the implementation commit.
- **Next Phase:** Finalize the Phase 7 report/provenance commit and tag, then benchmark the Phase 8 embedding/logistic router against the Keras DNN.

## Phase 7: Predictive risk (complete, 2026-11-02)

- **Status:** Complete; implementation commit `bae5771`; report/progress checkpoint tagged `phase-7-complete`.
- **What Was Built:** Train-only normalization and window features; factory-disjoint Logistic Regression/XGBoost baselines and PyTorch LSTM; early stopping; validation-only Platt calibration and promotion; test metrics with seeded bootstrap confidence intervals and reliability data; hashed, versioned local inference artifact; `make train` invokes the risk trainer.
- **What Was Measured:** Ruff and strict mypy passed; 70 tests passed; risk package coverage 167/167 (100%). CPU training took 10.369 seconds. Test AUROC/PR-AUC were 1.000 for all three models. XGBoost's test Brier was 0.000229 and ECE 0.006947; test confidence intervals are recorded for all metrics in `reports/risk.json`. Validation promotion correctly selected XGBoost because the LSTM failed the configured AUROC-margin rule. The report is tied to dataset split hashes, seed 42, and source SHA `bae57715b1f91c83f5c0dd67e8c26752958f6a8a`.
- **Deviations / Blockers:** Results are from synthetic data only and are not evidence of real-world predictive performance. The versioned joblib artifact is ignored/not committed; run `python ml/train_risk.py` to regenerate the report and artifact locally.
- **Next Phase:** Phase 8: benchmark the sentence-embedding/logistic router against the Keras DNN and document the winner.

## Phase 8: Intent router (complete, 2026-11-02)

- **Status:** Implementation commit `9a9ab50`; report and phase checkpoint are recorded in the `phase-8-complete` tag.
- **What Was Built:** Added six documented-by-name route classes, 144 manually authored unique queries (24 per intent), deterministic stratified train/validation/test splits, and a local inference API with artifact hash verification. The benchmark compares Logistic Regression with a Keras DNN on identical normalized 384-dimensional embeddings from a pinned MiniLM revision. Hugging Face model and tokenizer loads are local-cache-only. `reports/router.json` contains split IDs/counts, quality metrics, latency, token accounting, hashes, and the decision.
- **What Was Measured:** Python 3.12.10, TensorFlow 2.21.0/Keras 3.15.1, scikit-learn 1.9.1, sentence-transformers 6.2.0; CPU-only. Ruff passed; strict mypy passed across 73 application source files; all 79 tests passed and total application coverage was 93%. Both models tied on validation and test (accuracy 0.9655, macro-F1 0.9663), so the configured 0.01 validation macro-F1 improvement was not met and Logistic Regression was selected. On the 29-query test split, warm single-query p50/p95 latency was 9.81/10.90 ms for Logistic Regression and 65.68/67.78 ms for the DNN. The fake-LLM reference counted 1,213 input and 323 output tokens, estimated at $0.00037575 for the test split at illustrative rates; local routing's token-priced API spend is $0, a 100% reduction under that narrow cost definition. Repeat training reproduced the split, metrics, selected model, and artifact SHA-256.
- **Deviations / Blockers:** The labeled set is small and manually authored; measured quality is not a production accuracy claim. The token rates are illustrative and omit local compute. The pinned Apache-2.0-declared model must be present in the local Hugging Face cache; no model weights are committed. The DNN was evaluated but not saved because it did not win the validation promotion rule.
- **Next Phase:** Phase 9: implement the LangGraph orchestration and verify the Postgres-backed HITL restart/resume gate; this host has no Docker/PostgreSQL service.

## Phase 9: LangGraph orchestration (complete, 2026-11-02)

- **Status:** Implementation commit `024f997c4446d701a2e08cc8f68010c211e658a4`; initial checkpoint tag `phase-9-partial` retained; durable integration closure recorded in the `phase-9-complete` tag.
- **What Was Built:** Added routed graph paths for full analysis, retrieval-only, and out-of-scope requests; injected stage interfaces; deterministic verification and scorecard decisions; normal/critical risk escalation; validated human-review pause/resume; bounded retries for explicitly transient failures and a recursion limit; PostgreSQL checkpoint integration; and SQLAlchemy append-only audit recording. The explainer receives only a privacy-minimized, decision-locked context. Implementation and operational details are in `backend/app/graph/workflow.py` and `docs/graph.md`.
- **PostgreSQL evidence:** `test_postgres_checkpoint_survives_process_and_container_restart` starts a child at the HITL interrupt, terminates it, restarts the PostgreSQL Compose service, resumes in a new process, and verifies the scorecard, verdicts, persisted audit row, and audit hash chain. `test_postgres_checkpoint_runs_full_golden_set` executes all 150 golden scenarios through the PostgreSQL-backed graph and checks expected verdicts, escalation, scorecard, and audit events.
- **What Was Measured:** Ruff passed for `backend`, `scripts`, and `ml`; strict mypy passed across 74 application source files; the full suite passed (87 passed, zero skipped in 95.38 seconds), with 93% total application coverage. Both real PostgreSQL integration tests passed (2 passed in 50.40 seconds). These tests require the local Compose services and `TEST_DATABASE_URL`.
- **Deviations / Blockers:** The original master prompt and live-data addendum are not available in the checkout or session attachments; the implementation follows the supplied finish prompt where it defines requirements and does not infer unavailable details. Live-provider endpoint/license verification remains open for Phase 14. See ADR-012/014.
- **Next Phase:** Phase 10: implement the API, workers, rate limiting, and SSE using the available finish-prompt requirements.

## Environment bootstrap (2026-11-02)

- **Environment:** Docker Desktop CLI 29.9.2, Compose v5.6.1, Linux engine using WSL2. Added the local PostgreSQL 16/Redis 7 Compose stack, health checks, named volumes, init SQL creating `ecochain_test`, Windows PowerShell runbook, `.gitattributes` LF rules, and `infra-up`/`infra-down`/`infra-reset`/`test-int` targets. The root `.env` was created locally, is git-ignored, and contains development-only service credentials plus generated local application keys.
- **Verified services:** PostgreSQL and Redis both reached healthy status. Migrations succeeded on `ecochain`; `ecochain_test` succeeded through upgrade, downgrade to base, and re-upgrade to revision `2026_11_02_0003`. Redis `PING` returned `PONG`.
- **Gate:** Ruff and strict mypy pass; services are healthy; schema migration and rollback checks succeeded. See the Phase 9 section above for the final full-suite result.
- **Prompt availability:** Preserved the available resume and finish prompts in `docs/prompts/`. The master prompt and live-data addendum were not present in the checkout or available attachments and have not been fabricated; see `docs/prompts/README.md`.
- **Local note:** `.env` is ignored and not committed. `TEST_DATABASE_URL` points to `127.0.0.1` because Psycopg's raw connection otherwise stalls while resolving Windows `localhost` to IPv6 before trying Docker's IPv4 loopback binding.

## Phase 10: API, workers, SSE (partial, 2026-11-02)

- **What Was Built:** Added FastAPI `/v1` routers for token issuance, tenant-scoped jobs/documents, reviews, factories, audit events, integrations, lookup settings, and regulation proposals. Passwords use Argon2; signed JWT principals carry UUID user/tenant IDs and role. Repository methods include the tenant predicate in each resource lookup. Upload validation enforces count/size/type/PDF magic/page limits and deduplicates identical documents; job idempotency hashes the sorted unique document-hash set per tenant.
- **Async work and events:** Added a Redis-backed atomic fixed-window rate limiter, per-job Redis Streams, replay/tailing by `Last-Event-ID`, JSON-only summary events, Celery job/review-resume tasks, PostgreSQL graph checkpoint use, and tenant-bound review decisions. Added migration `2026_11_02_0003_api_submissions.py` for query/idempotency metadata, tenant settings, document associations, and proposal tenant ownership. `make build` exports `frontend/openapi.json`.
- **What Was Measured:** Ruff passed (`backend`, `scripts`); strict mypy passed (84 application files); full suite passed (94 passed, zero skipped in 117.03 seconds) with 85% total app coverage. The real-service integration test passed against Compose PostgreSQL and Redis, covering resource tenant denial, rate limiting, upload abuse, SSE replay/reconnect, and the explicit 503 fail-closed path. Migration 0003 upgrade/downgrade/re-upgrade passed on both databases.
- **Deviations / Blockers:** The graph defines explicit `WorkflowServices` interfaces but this checkout contains no production service assembly. The worker requires `WORKFLOW_SERVICES_FACTORY=module:factory`; no fake implementation is supplied. Therefore full job execution and API-driven HITL pause/resume are not verified; uploads/readiness/review decisions fail closed. This partial checkpoint is tagged `phase-10-partial`, not `phase-10-complete`. The original master prompt and live-data addendum remain unavailable.
- **Next Phase:** Complete and test a production `WorkflowServices` factory, then prove full job flow and API HITL with real PostgreSQL/Redis before starting Phase 11.
