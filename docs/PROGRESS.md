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

- **Status:** Partial pending PostgreSQL verification of audit-trigger migration 0004.
- **What Was Built:**
  - `core/config.py`: `pydantic-settings` configuration supporting dynamic model selection via `GEMINI_MODEL`, risk/verification thresholds, database and security settings.
  - `core/logging.py`: Structured JSON logging with `PIISafeFilter` (redacts emails, IBANs, phone numbers, cards) and contextual correlation (`job_id`, `thread_id`, `tenant_id`).
  - `core/errors.py`: Standard domain exception hierarchy with typed error codes (`EcoChainError`, `ValidationError`, `PrivacyViolationError`, `AuditChainTamperError`, `TenantIsolationError`).
  - `domain/models.py`: Complete domain contracts: `BBox` (normalized 0-1000 with validation), `ExtractedField`, `EvidenceItem`, `Claim` (strictly requiring evidence IDs), `Verdict`, `RiskForecast`, `DocumentRef`, `RedactedPage`, `EscalationState`, `ScorecardLine`, `Scorecard`, and `GraphState` with append-only reducers.
  - `db/models.py`: SQLAlchemy ORM models for `tenants`, `users`, `factories`, `documents`, `jobs`, `reviews`, and `audit_events`. ORM guards are backed by migration `2026_11_02_0004_audit_append_only.py`, which creates database triggers to prevent `UPDATE` and `DELETE`.
  - `db/audit_log.py`: Append-only cryptographic audit logger with SHA-256 hash chaining (`prev_hash`, `event_hash`) and full chain verification via `verify_chain()`.
  - `alembic.ini` and initial migration `2026_11_02_0001_initial_schema.py`: tested clean upgrade, rollback (downgrade), and re-upgrade.
- **What Was Measured:**
  - Ruff linter: green (0 errors).
  - Mypy type checker: green under strict mode on `backend/app` (0 issues across 26 source files).
  - Targeted audit/domain tests: 9 passed; SQLite raw SQL mutations are blocked and privileged trigger bypass remains detectable by the hash chain.
- **Deviations / Blockers:**
  - PostgreSQL verification is pending because Docker Desktop's engine is unavailable. A full SQLite migration smoke test stops at pre-existing migration `2026_11_02_0003_api_submissions.py`, which uses SQLite-unsupported `ALTER COLUMN ... DROP DEFAULT`.
- **Next Phase:** Phase 2: Data (Synthetic and Real).

---

## Phase 2: Data (Synthetic and Real)

- **Status:** Partial: audit-history and manifest requirements pass, but document corpus requirements do not.
- **What Was Built:**
  - `scripts/generate_issuer_registry.py`: Approved mock certificate issuer registry (`data/registry/approved_issuers.csv`) covering Control Union, Ecocert, OEKO-TEX, SGS, Intertek, Bureau Veritas, and TÜV Rheinland.
  - `scripts/generate_regulations.py`: Versioned legal texts in `data/regulations/csddd_regulations.json`, including the superseded Directive (EU) 2024/1760 and the in-force Omnibus I Directive (EU) 2026/470 and ESPR (EU) 2024/1781.
  - `scripts/generate_audit_histories.py`: 450 factories generated with 36-month time series of numeric signals (`carbon_intensity`, `labor_violations`, `cert_lapse_days`, `corrective_action_backlog`, `safety_incidents`). Grounded in a latent hazard process with drift and seasonality. Stratified 70/15/15 train/val/test split by factory.
  - `scripts/generate_documents.py`: 180 synthetic PDFs generated with PyMuPDF (120 clean, 60 adversarial spanning expired validity, unapproved/fuzzy issuers, and scope/facility mismatches), with normalized bounding boxes (0-1000) and embedded privacy seeds (`PERSON`, `EMAIL_ADDRESS`, `IBAN_CODE`, `PRICE`). This is below the master prompt's "hundreds" requirement; scan noise, skew, stamps/signatures, and all requested document types are not evidenced.
  - `scripts/generate_golden_set.py`: 150 labeled end-to-end evaluation cases in `data/golden/golden_set.json` with expected verdicts and escalation flags.
  - `scripts/generate_synthetic_data.py`: Master generation entrypoint and SHA-256 integrity validator outputting `data/MANIFEST.json`.
- **What Was Measured:**
  - `data/MANIFEST.json`: 7 files cryptographically hashed and verified byte-identical.
  - Total test suite: 16 unit tests passing in 2.29s.
  - Ruff linter & Mypy strict: green across all modules.
- **Deviations / Blockers:**
  - PDF binary outputs are gitignored to preserve repo compactness; generation is deterministic from `SEED=42` and reproducible via `make data`. The corpus must be expanded before Phase 2 can be considered conformant.
- **Next Phase:** Phase 3: Privacy Boundary (OCR, Presidio + regex redaction, Llama checker, Vault, OutboundGuard, Leakage suite).

---

## Phase 3: Privacy Boundary

- **Status:** Complete (Gate Passed)
- **What Was Built:**
  - `config/recognizers.yaml`: Presidio and regex recognizer specifications for prices, IBANs, phone numbers, supplier IDs, and facility IDs.
  - `privacy/ocr.py`: `IOcrEngine` interface with `PyMuPdfOcrEngine` local text and word bounding box extraction normalized to the 0-1000 LayoutLM space.
  - `privacy/vault.py`: `TokenVault` providing per-tenant reversible AES-256 Fernet tokenization (`[PERSON_001]`, `[IBAN_CODE_001]`, etc.), deterministic detokenization, rehydration, and sensitive entity tracking.
  - `privacy/redactor.py`: `DocumentRedactor` combining Presidio `AnalyzerEngine`, custom regex recognizers, template stopword filtering, and bbox preservation into `RedactedPage`.
  - `privacy/llama_checker.py` and `integrations/ollama.py`: Second-pass local sensitive data inspector using Ollama with fail-closed behavior (`FakeLlamaChecker` for tests); HTTP requests require tenant-scoped `OutboundGuard` validation.
  - `privacy/outbound_guard.py`: Single choke-point for all cloud LLM requests enforcing image byte elimination, 500k char size limits, zero vault-known value leakage, and outbound payload hashing to the audit log.
  - `tests/leakage/test_privacy_leakage.py`: Leakage test suite across 180 documents (720 privacy seeds), cloud LLM import checks, and network-library confinement to `integrations/` and `llm/`.
- **What Was Measured:**
  - `reports/redaction.json`: 720/720 seeded PII items detected (100% recall across `PERSON`, `EMAIL_ADDRESS`, `IBAN_CODE`, `PRICE`).
  - Total leakage rate: 0.0% (zero seeded values leaked into outbound payloads).
  - Total test suite: 22 unit & leakage tests passing in 16.4s.
  - Ruff linter & Mypy strict: green across 31 source files.
- **Deviations / Blockers:**
  - Template label words (`facility`, `supplier`, etc.) are filtered from entity tokenization to prevent template headers from colliding with sensitive entity checks. Live third-party provider adapters are not yet implemented.
- **Next Phase:** Phase 4: Extraction (Base interface, LayoutLMv3, Heuristic extractor, normalizers, evaluation script).

## Phase 4: Extraction

- **Status:** Partial. Heuristic extraction and the report exist; LayoutLMv3 training/inference is still a stub.
- **Evidence:** `backend/app/extraction/layoutlmv3.py` always returns heuristic results; `ml/train_layoutlm.py` evaluates the heuristic extractor and substitutes a default IoU when no boxes are measured. `reports/extraction.json` must not be interpreted as LayoutLMv3 performance.
- **Next:** Implement actual fine-tuning, model loading/inference, and held-out evaluation before marking the phase conformant.

## Phase 5: Compliance RAG

- **Status:** Offline gate closed. Real local CrossEncoder reranking, parent-linked regulation chunks, approval-gated versioned ingestion, and local answerability checks are implemented. The full semantic acceptance remains incomplete because Ragas is `not_run`.
- **Evidence:** `reports/rag.json` records 60-query precision@5 `0.20`, recall@5 `1.00`, MRR@5 `0.9833`; date-filter violations `0`; no-support accuracy `1.00`; supported-query recall `0.90`; and BM25-only/dense-only/hybrid/hybrid+rerank metrics. The 80-query answerability threshold was selected on that same set, so it is not an independent holdout estimate. All 24 RAG unit tests pass; targeted Ruff and strict mypy pass.
- **Ragas:** Faithfulness and answer relevance are `not_run` with reason `API keys not available`; no provider calls were made. To run later, set `GOOGLE_API_KEY` and `OPENAI_API_KEY`, then run `.\.venv\Scripts\python.exe -m scripts.evaluate_rag --allow-external-model-calls`. The call may incur charges.
- **Dependencies:** `langchain-community==0.3.31` keeps the Ragas compatibility import available; ADR-016 records the compatibility pin, ADR-017 the metric thresholds/privacy boundary, and ADR-018 the offline closure and limitation.
- **Next:** Phase 10 missing routes and production `WorkflowServices` assembly, using `LLM_PROVIDER=fake` in the test/runtime configuration.

---

## Recovery checkpoint and Phase 6 (2026-11-02)

- **Historical recovery note:** This checkpoint predates prompt restoration and the current conformance audit. The active master/addendum specs now exist under `docs/prompts/`; see `docs/CONFORMANCE.md` for current status.
- **Gate from the repository root:** Ruff passed; strict mypy passed with no issues across 52 source files; pytest passed (50 passed). The implemented verifier package has 100% statement coverage (158/158 statements); total application coverage is 92%.
- **Phase 6 status:** Partial. Nine rule functions (V-EXP-001/002, V-DATE-001, V-ISS-001/002, V-SCOPE-001/002, V-XDOC-001/002) now produce the canonical evidence-linked `Verdict`; their boundary tests pass with 100% statement coverage. The mock issuer registry loader is implemented and emits a visible `MOCK` warning.
- **Initial checkpoint gaps (resolved later):** At that time the verifier engine, V-PAGE/V-CONF/V-EXT/V-SANC rules, provider fakes, and report were missing. The active conformance audit verifies the current implementation.
- **Contract decision:** ADR-008 records the canonical verdict shape and V-DATE-001 escalation behavior.
- **Windows services checked:** Python 3.12.10, Node, and npm are available. Tesseract, Ollama, Redis CLI, PostgreSQL CLI, and Docker are not available on PATH; service-backed integration checks remain blocked.
- **Next action:** Restore `ECOCHAIN_MASTER_PROMPT.md` and `ECOCHAIN_ADDENDUM_LIVE_DATA.md`, then implement and test the remaining verifier rules against those specifications.

## Phase 6 implementation checkpoint (2026-11-02, updated 2026-11-03)

- **Status:** Complete for deterministic implementation and unit gates; current external-rule semantics were corrected against Addendum A3.
- **What Was Built:** Added the remaining page-count, confidence, external snapshot, provider-outage, and sanctions rules; deterministic `Verifier` orchestration; validated `config/verifier.yaml` thresholds; snapshot/provider contracts and deterministic fakes; critical/normal escalation priority; and a seeded golden evaluator. Corrected the golden fixture's page-count field and fuzzy issuer example.
- **What Was Measured:** Python 3.12.10; Ruff clean; strict mypy clean across 64 source files; 63 tests passed; verifier package coverage 397/397 statements (100%). The synthetic golden evaluator matched 150/150 expected rule verdicts and 150/150 escalation outcomes. The seeded data manifest verifies.
- **Deviations / Blockers:** The existing golden set has no expected V-EXT/V-SANC labels; dedicated boundary tests cover those outcomes. `reports/verifier.json` was regenerated after implementation commit `79e037b`.
- **Current next phase:** Phase 5 offline closure is complete; resume Phase 10. Phase 7's validation-only calibration and promotion requirements remain met.

## Phase 6: Deterministic verifier (complete, 2026-11-02)

- **Status:** Complete; implementation commit `0a64e25`. The phase tag is applied to the report/progress checkpoint commit.
- **What Was Built:** All 17 verifier rules are orchestrated in deterministic order over evidence-linked claims and vault-mapped context. Added the missing eight rules, validated YAML thresholds, local snapshot provider contracts/fakes, and explicit `normal`/`critical` escalation priority. Added seeded golden evaluation and corrected the page-count fixture key.
- **What Was Measured:** Ruff clean; strict mypy clean across 64 source files; 63 tests passed; all 397 statements in `backend/app/verifier/` covered (100%). `reports/verifier.json` records 150/150 expected verdicts and 150/150 expected escalation outcomes, dataset SHA-256 `b03022a6d195729e038ba07f311ebc3b846c33125b8943cb75610af86b5a78a3`, seed 42, and source commit `0a64e25`. `data/MANIFEST.json` verifies.
- **Deviations / Blockers:** The synthetic golden set has no expected V-EXT/V-SANC labels; its 100% figure measures only the labels it contains. The rule tests now match Addendum A3; see ADR-009 and `docs/CONFORMANCE.md`.
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

## Phase 9: LangGraph orchestration (implementation complete; conformance partial)

- **Status:** Implementation commit `024f997c4446d701a2e08cc8f68010c211e658a4`; initial checkpoint tag `phase-9-partial` retained; durable integration closure recorded in the `phase-9-complete` tag.
- **What Was Built:** Added routed graph paths for full analysis, retrieval-only, and out-of-scope requests; injected stage interfaces; deterministic verification and scorecard decisions; normal/critical risk escalation; validated human-review pause/resume; bounded retries for explicitly transient failures and a recursion limit; PostgreSQL checkpoint integration; and SQLAlchemy append-only audit recording. The explainer receives only a privacy-minimized, decision-locked context. Implementation and operational details are in `backend/app/graph/workflow.py` and `docs/graph.md`.
- **PostgreSQL evidence:** `test_postgres_checkpoint_survives_process_and_container_restart` starts a child at the HITL interrupt, terminates it, restarts the PostgreSQL Compose service, resumes in a new process, and verifies the scorecard, verdicts, persisted audit row, and audit hash chain. `test_postgres_checkpoint_runs_full_golden_set` executes all 150 golden scenarios through the PostgreSQL-backed graph and checks expected verdicts, escalation, scorecard, and audit events.
- **What Was Measured:** Ruff passed for `backend`, `scripts`, and `ml`; strict mypy passed across 74 application source files; the full suite passed (87 passed, zero skipped in 95.38 seconds), with 93% total application coverage. Both real PostgreSQL integration tests passed (2 passed in 50.40 seconds). These tests require the local Compose services and `TEST_DATABASE_URL`.
- **Deviations / Blockers:** Addendum A4's graph stage exists, but local snapshot enrichment is not assembled into production `WorkflowServices`; live-provider endpoint/license verification remains open for Phase 14. See ADR-012/014.
- **Next Phase:** Phase 10: implement the API, workers, rate limiting, and SSE using the available finish-prompt requirements.

## Environment bootstrap (2026-11-02)

- **Environment:** Docker Desktop CLI 29.9.2, Compose v5.6.1, Linux engine using WSL2. Added the local PostgreSQL 16/Redis 7 Compose stack, health checks, named volumes, init SQL creating `ecochain_test`, Windows PowerShell runbook, `.gitattributes` LF rules, and `infra-up`/`infra-down`/`infra-reset`/`test-int` targets. The root `.env` was created locally, is git-ignored, and contains development-only service credentials plus generated local application keys.
- **Verified services:** PostgreSQL and Redis both reached healthy status. Migrations succeeded on `ecochain`; `ecochain_test` succeeded through upgrade, downgrade to base, and re-upgrade to revision `2026_11_02_0003`. Redis `PING` returned `PONG`.
- **Gate:** Ruff and strict mypy pass; services are healthy; schema migration and rollback checks succeeded. See the Phase 9 section above for the final full-suite result.
- **Prompt availability:** All four active prompts are present in `docs/prompts/`; see `docs/prompts/README.md`.
- **Local note:** `.env` is ignored and not committed. `TEST_DATABASE_URL` points to `127.0.0.1` because Psycopg's raw connection otherwise stalls while resolving Windows `localhost` to IPv6 before trying Docker's IPv4 loopback binding.

## Phase 10: API, workers, SSE (initial partial checkpoint, superseded 2026-11-03)

- **What Was Built:** Added FastAPI `/v1` routers for token issuance, tenant-scoped jobs/documents, reviews, factories, audit events, integrations, lookup settings, and regulation proposals. Passwords use Argon2; signed JWT principals carry UUID user/tenant IDs and role. Repository methods include the tenant predicate in each resource lookup. Upload validation enforces count/size/type/PDF magic/page limits and deduplicates identical documents; job idempotency hashes the sorted unique document-hash set per tenant.
- **Async work and events:** Added a Redis-backed atomic fixed-window rate limiter, per-job Redis Streams, replay/tailing by `Last-Event-ID`, JSON-only summary events, Celery job/review-resume tasks, PostgreSQL graph checkpoint use, and tenant-bound review decisions. Added migration `2026_11_02_0003_api_submissions.py` for query/idempotency metadata, tenant settings, document associations, and proposal tenant ownership. `make build` exports `frontend/openapi.json`.
- **What Was Measured:** Ruff passed (`backend`, `scripts`); strict mypy passed (84 application files); full suite passed (94 passed, zero skipped in 117.03 seconds) with 85% total app coverage. The real-service integration test passed against Compose PostgreSQL and Redis, covering resource tenant denial, rate limiting, upload abuse, SSE replay/reconnect, and the explicit 503 fail-closed path. Migration 0003 upgrade/downgrade/re-upgrade passed on both databases.
- **Deviations / Blockers:** The graph defines explicit `WorkflowServices` interfaces but this checkout contains no production service assembly. The worker requires `WORKFLOW_SERVICES_FACTORY=module:factory`; no fake implementation is supplied. Required scorecard/rendered-page/query/factory-risk routes are also absent, and the integration status route does not use the specified `/status` suffix. Full job execution and API-driven HITL pause/resume are not verified; uploads/readiness/review decisions fail closed. This partial checkpoint is tagged `phase-10-partial`, not `phase-10-complete`.
- **Next Phase:** Complete and test a production `WorkflowServices` factory, then prove full job flow and API HITL with real PostgreSQL/Redis before starting Phase 11.

## Conformance audit checkpoint (2026-11-03)

- Added `docs/CONFORMANCE.md`, comparing Phases 1-10, section 5 contracts, Addendum R1-R4, and acceptance items 1-20.
- Safety fixes committed: `c82aa4f` (audit triggers and external refs), `b1122d1` (guarded Ollama), `79e037b` (EXT/SANC semantics), and `ff93818` (100% Verifier coverage).
- Targeted validation: 25 Verifier tests pass with 100% statement coverage (402/402); audit/domain/privacy targeted tests pass (17 passed); Ruff and strict mypy pass for changed application files.
- The new PostgreSQL audit-trigger migration remains pending PostgreSQL verification. Phase 5 offline closure is complete; Phase 10 is next.

## Phase 9/10 closure (2026-11-03)

- **Phase 9 local enrichment:** Wired the `enrich` graph stage to tenant-scoped local snapshots through `backend/app/graph/services.py`. Facility and sanctions evidence retain snapshot hash, source, fetch time, and record key. No live provider calls are made; missing data escalates. The graph restart/resume and golden-set integration gates pass.
- **Phase 10 API completion:** Added the scorecard, rendered-PDF/ETag, RAG query, factory-risk, `/v1/integrations/status`, and regulation-proposal decision routes. Added local workflow assembly with `LLM_PROVIDER=fake`, a deterministic fake explainer, and fail-closed production behavior when approved risk history is unavailable.
- **Phase 10 gate:** Python 3.12.10; Ruff passed for `backend`, `scripts`, and `ml`; strict mypy passed across 97 application files; 10 targeted unit/e2e tests passed. `scripts/test_integration.ps1` passed all 4 real PostgreSQL/Redis tests (API tenant boundaries, upload/rate limits, SSE replay, real Celery full job and API HITL pause/resume, Postgres restart/resume, and the 150-case graph golden set). OpenAPI export succeeded.
- **Repeatability fix:** API integration snapshot fixture now uses a per-run source ID and removes only its own source and dependent snapshot rows. Status assertions account for snapshots already present in the persistent test database and verify each tenant's live-lookup setting.
- **Limitations / ADR-019:** The local factory uses no live external provider. Synthetic audit history is development-only; production fails closed when approved history is absent. Live provider integration remains Phase 14. Ragas semantic metrics remain `not_run`; the Phase 2 corpus and Phase 4 model limitations remain open.
- **Next Phase:** Phase 11 frontend; first verify and pin the available Node.js and package-manager versions.

## Phase 11 verification checkpoint (2026-11-10)

- **Phase 11 status:** Complete (all requested frontend, browser E2E, migration, and real PostgreSQL/Redis integration gates passed). Phase 12 had not started at this checkpoint.
- **Frontend:** Next.js login and protected workspace, tenant-scoped jobs/PDF upload, live job SSE, evidence-linked scorecard and PDF overlays, human review decisions, factory risk, audit, and integrations are implemented. Access tokens remain in an HTTP-only SameSite cookie; the same-origin proxy forwards backend requests and streams SSE.
- **Frontend gates (exit code 0 for each):** `npm run lint`; `npm run typecheck`; `npm test -- --reporter=dot` (4 files, 7 tests passed); `npm run build`; `npm run test:e2e -- --reporter=list` (3 tests passed). Playwright 1.65.0 Chromium 1254 was present. The browser journey covers sign-in, protected dashboard, PDF upload, SSE display, scorecard, evidence/PDF overlay, review submission, and factory risk, audit, and integrations. E2E API calls use route fixtures; real service behavior is verified separately by the integration suite.
- **Real services and migrations:** Existing Compose PostgreSQL 16 and Redis 7 containers reported healthy. `pg_isready` accepted connections and Redis returned `PONG`. Alembic reported `2026_11_02_0004 (head)` on both `ecochain` and `ecochain_test`.
- **Integration gate:** `scripts/test_integration.ps1` ran with the project `.venv` against the real services and passed (5 passed, 114 deselected, exit code 0; 63.74 seconds). This exercised tenant isolation, rate limiting, SSE replay, Celery workflow/HITL pause-resume, PostgreSQL process/container restart, the golden graph set, and append-only audit events. No mocks replaced these tests.
- **Runtime artifacts:** The downloaded checkout lacked ignored router and risk model files. Rebuilt them with the project trainers using local data/cache and checked their bytes against the tracked manifests: router SHA-256 `91c0e6c9dfa4dba7d15e651315ad946d37b87d8c00f9e6ea4c020f9b8fa84134`; risk SHA-256 `a8984b1e4175e845e7e0206e24a7d28a8e1e390268b0b7ab257b0301c305c3d1`. The tracked evaluation reports were not rewritten.
- **Environment and Git:** Python 3.12.11 `.venv`; Node 22.23.4 / npm 10.9.0. `.git` is absent from both the project and its opened parent; `git rev-parse --show-toplevel` returned 128. No repository was initialized and no existing work was overwritten. Restore the authoritative Git checkout before any commit or history operation.
- **At this checkpoint:** Phase 11 gates were complete and Phase 12 was not yet authorized; the user has since requested continuation. Phase 12 work and current status are recorded below.

## Phase 12 evaluation and packaging checkpoint (2026-11-11)

- **Phase 12 status:** Complete. At this checkpoint, local evaluation, image build, full-stack readiness, migration, and demo gates all passed; Phase 13 work is recorded below.
- **Evaluation/demo:** `reports/evaluation_report.md` reports 22/22 aggregate gates passed. The verifier golden set is rerun; extraction, privacy, RAG, risk, and router metrics are loaded from their versioned reports. The deterministic demo passed all 150/150 expected verdicts and 150/150 escalations. Ragas faithfulness/relevance remain `not_run`.
- **Regression tests and static checks:** Three evaluation-gate tests passed. Full Ruff checks for `backend`, `scripts`, and `ml` and strict mypy for 99 application files passed; targeted Ruff and strict mypy also passed for the final model-download and evaluation scripts.
- **Backend validation:** Full `pytest backend/tests -v --cov=backend/app --cov-report=term-missing` passed (122 passed, 82% coverage), including all five real PostgreSQL/Redis integration tests. Both databases were upgraded to head first. Docker Desktop stopped during an initial attempt; it was restarted and the full suite then passed.
- **Frontend validation:** `npm run lint`, `npm run typecheck`, `npm test` (7 passed), standalone `npm run build`, and `npm run test:e2e` (3 passed) all passed.
- **Packaging/CI:** Added multi-stage backend/Next.js Docker images, a pinned CPU runtime dependency lock, root full-stack Compose services (database, cache, migration, API, worker, frontend), and a CI workflow for live-service tests, browser tests, evaluation/demo, and container smoke tests. All images built successfully. The root Compose stack started with `docker compose up -d --wait`; PostgreSQL and Redis were healthy, migrations reached `2026_11_02_0004 (head)`, the API returned `{"status":"ready"}`, frontend `/login` returned HTTP 200, and the containerized golden demo passed. The full-stack check used host ports 5433/6380 to preserve the existing dev services on 5432/6379. The GitHub Actions workflow was authored but not run from this checkout.
- **Limitations/environment:** Aggregate model metrics are read from versioned reports rather than retrained; optional Ragas metrics remain `not_run`. Python commands use `.venv\Scripts\python.exe`. Git metadata is absent; no repository was initialized and no commit was attempted.

## Phase 13 security hardening checkpoint

- **Status:** Partial. Security hardening tests, real-service outage recovery, static checks, and coverage gates pass. Do not start Phase 14.
- **Implementation and tests:** Added prompt-injection verdict-invariance tests, adversarial explanation coverage, fail-closed Ollama-unavailable coverage, auth/RBAC and cross-tenant review denials, PostgreSQL audit-chain tamper coverage, and a real PostgreSQL/Redis mid-job outage-and-recovery test. Existing malformed/oversized PDF and PII-leakage tests remain in the full suite. Redis rate-limit failures return 503; worker failure/lock cleanup now logs cleanup errors without masking the original exception.
- **Full backend gate:** `.venv\Scripts\python.exe -m pytest backend\tests -v --cov=backend/app --cov-report=term-missing` passed (134 passed, exit code 0, 292.13 seconds), with 90% total application coverage. All seven integration tests used real PostgreSQL/Redis; none were replaced with mocks. The new `test_graph_services.py` tests passed (8 passed) and brought `backend/app/graph/services.py` to 98% coverage. `verifier/`, `privacy/`, `graph/`, and `domain/` each meet the Phase 13 85% minimum.
- **Static checks:** Ruff passed for `backend`, `scripts`, and `ml`; strict mypy passed for 99 application files.
- **Service evidence:** Compose PostgreSQL 16 and Redis 7 were healthy after the outage suite. `SELECT 1` succeeded against both `ecochain` and `ecochain_test`.
- **Documentation:** Added root README quickstart port separation, safe `.env` setup guidance, PowerShell execution-policy fallback, and concrete direct pytest/test-service configuration instructions to the runbook.
- **Quickstart runtime check (2026-11-11):** Docker Desktop 29.9.3 / Compose 5.7.0 became available after restart. From this working tree, `docker compose up -d --build --wait` exited 0 with `POSTGRES_PORT=5433` and `REDIS_PORT=6380`; PostgreSQL, Redis, API, worker, and frontend started, the migration service exited 0, and the API database reported `2026_11_02_0004 (head)`. `/readyz` returned `{"status":"ready"}`, `/login` returned HTTP 200, PostgreSQL accepted connections, Redis returned `PONG`, and `docker compose exec -T api python -m scripts.run_demo` passed 150/150 verdicts and escalations. This verifies the documented runtime steps against the current working tree, not from a clean clone.
- **Acceptance blocker:** A clean-clone check remains unverified. The supplied repository `https://github.com/SumukhMSortur/AgenticAI` has only `main` at `035fb75b3e3735a706234d36a0ba1f37d3b35b8c` (2026-11-03, Phase 10); it does not contain this workspace's Phase 12/13 state or current README, SECURITY.md, and Graph service tests. The nearby ZIP is likewise stale. The temporary clone was kept separate and not overlaid with this workspace, since doing so would not be a genuine clean clone. No existing work was discarded, no replacement repository was initialized, and no commit or tag was attempted. An updated branch/commit matching the current workspace is required before marking Phase 13 complete.
