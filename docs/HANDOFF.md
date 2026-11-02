# EcoChain Copilot Handoff

| Phase | Status (done / partial / not started) | Tag | Tests | Metrics produced (file) | Deviations and ADRs | Blockers |
|---|---|---|---|---|---|---|
| 0 Recon, plan, skeleton | done | `phase-0-complete` | Current full gate passes | — | Historical record in `docs/PROGRESS.md` | None known |
| 1 Foundations | done | `phase-1-complete` | Current full gate passes | — | Verdict contract reconciliation is ADR-008 | None known |
| 2 Data | done | `phase-2-complete` | Data tests pass | `data/MANIFEST.json` | Generated data is local/ignored | None known |
| 3 Privacy boundary | done | `phase-3-complete` | Leakage tests pass | `reports/redaction.json` | External services unavailable locally | Docker not installed |
| 4 Extraction | done | `phase-4-complete` | Extraction tests pass | `reports/extraction.json` | Historical phase evidence is not fully recorded in `docs/PROGRESS.md` | None known |
| 5 Compliance RAG | partial | `phase-5-complete` | Current RAG tests pass | No `reports/rag.json` found | Tag exists, but phase acceptance evidence is incomplete | RAG report/phase gate evidence |
| 6 Deterministic verifier | done | `phase-6-complete` | Ruff, strict mypy, 63 tests; verifier package 100% statement coverage; golden result 150/150 | `reports/verifier.json` | ADR-008/009; external semantics conservatively inferred because Addendum A3 is missing | Addendum A3 semantics are unverified; no expected EXT/SANC golden labels |
| 7 Predictive risk | done | `phase-7-complete` | Ruff, strict mypy, 70 tests; risk package 100% statement coverage; CPU training/inference verified | `reports/risk.json` | ADR-010; synthetic-only metrics; XGBoost selected using validation metrics | Trained weights are local/ignored and must be regenerated for inference |
| 8 Intent router | done | `phase-8-complete` | Ruff, strict mypy, 79 tests; 93% total app coverage; repeated benchmark reproduced metrics and artifact hash | `reports/router.json` | ADR-011; DNN tied baseline and was not retained | Local MiniLM cache required; small labeled query set |
| 9 LangGraph orchestration | partial | `phase-9-partial` | Ruff, strict mypy; 86 passed; 92% total app coverage | — | ADR-012; in-memory golden workflow and same-process Postgres saver test pass | Required child-process kill/restart, container-restart resume, and Postgres golden-set gates remain |
| 10 API, workers, SSE | not started | — | — | — | — | Implementation not started |
| 11 Frontend | not started | — | — | — | — | Frontend files/package manifest not yet verified |
| 12 Evaluation, CI, Docker | not started | — | — | — | — | Full-stack Docker/CI implementation not started |
| 13 Hardening | not started | — | — | — | — | Service-backed outage tests not run |
| 14 Live integrations | not started | — | — | — | ADR-007/009 | Addendum A5 absent; live-provider terms/endpoints must be verified before wiring |

## Current checkpoint

- **Phase 6 implementation commit:** `0a64e25` (`feat(verifier): complete deterministic verification engine`).
- **Phase 6 gate (run from the repository root, Python 3.12.10):** Ruff passed; strict mypy passed across 64 source files; pytest passed (63 passed); verifier package coverage is 100% (397/397 statements). Golden evaluation: 150/150 expected verdicts and 150/150 escalation results; report dataset SHA-256 is `b03022a6d195729e038ba07f311ebc3b846c33125b8943cb75610af86b5a78a3`, seed 42; `data/MANIFEST.json` verifies.
- **Phase 7 gate:** Ruff and strict mypy passed; pytest passed (70 passed); risk package statement coverage is 100% (167/167). The CPU training run, deterministic metrics/artifact hash, and XGBoost inference were verified.
- **Phase 7 implementation/report:** `bae5771` (`feat(risk): train and evaluate calibrated risk models`); report source SHA matches. Test metrics for served XGBoost: AUROC 1.000, PR-AUC 1.000, Brier 0.000229, ECE 0.006947; all models and 95% bootstrap intervals are in `reports/risk.json`. CPU run: 10.369 seconds; the model artifact SHA is recorded in the report but the artifact is not committed.
- **Phase 8 implementation/report:** `9a9ab50` (`feat(router): add offline intent routing benchmark`); `reports/router.json` source SHA matches. The 144-query set is split 86/29/29 with near-equal per-intent representation. Logistic Regression and the DNN tied at validation/test accuracy 0.9655 and macro-F1 0.9663; the DNN failed the required validation margin and is not retained. Logistic Regression warm CPU p50/p95 latency was 9.81/10.90 ms versus 65.68/67.78 ms for the DNN. The test-set fake-LLM reference counted 1,213 input and 323 output tokens and estimated $0.00037575 at illustrative rates; local token-priced API spend was $0. The report and local artifact SHA were reproduced on a second training run.
- **Phase 9 implementation:** `024f997` (`feat(graph): implement bounded compliance workflow`). Added routed LangGraph stages, deterministic verification/scoring, bounded transient retries and recursion, validated HITL interrupt/resume, PostgreSQL checkpoint support, and append-only SQLAlchemy audit recording. See `docs/graph.md`.
- **Phase 9 gate:** Ruff passed; strict mypy passed across 74 application source files; full pytest passed (85 passed, 1 skipped in 43.31 seconds) with 92% total app coverage. The focused graph gate passed (6 passed); the durable PostgreSQL restart/resume integration test was skipped because `ECOCHAIN_TEST_POSTGRES_URL` is unset and this host has no PostgreSQL service. The phase is intentionally partial; the in-memory tests do not substitute for the persistence gate.
- **Environment bootstrap (2026-11-02):** Docker CLI `29.9.2`, Compose `v5.6.1`, engine on Docker Desktop/WSL2. Added `docker/compose.dev.yml` for PostgreSQL 16 and Redis 7, with health checks and named volumes; both containers became healthy on free host ports 5432/6379. The root `.env` is local/ignored and uses development-only credentials; `.env.example` lists application/test database and Redis URLs. Both databases migrated to head; `ecochain_test` also passed `upgrade head` → `downgrade base` → `upgrade head` (final revision `2026_11_02_0002`). Redis `PING` returned `PONG`.
- **Step E gate:** Ruff passed (`backend`, `scripts`, `ml`); strict mypy passed across 74 app files; the full suite passed (86 passed, no skips, 111.67 seconds), total app coverage 92%. This includes a same-process PostgreSQL saver restart test only; Phase 9 remains partial pending the stronger process/container restart evidence below.
- **Prompt persistence:** `docs/prompts/RESUME_PROMPT.md` and `docs/prompts/FINISH_PROMPT.md` preserve the two available source prompts. The original `ECOCHAIN_MASTER_PROMPT.md` and `ECOCHAIN_ADDENDUM_LIVE_DATA.md` were not found in the repository or session attachments, so their contents were not fabricated. See `docs/prompts/README.md`.
- **How to run the gate on Windows PowerShell:**

  ```powershell
  Set-Location "E:\AgenticAI project\AgenticAI"
  .\.venv\Scripts\python.exe -m ruff check backend
  .\.venv\Scripts\python.exe -m mypy --strict backend\app
  .\.venv\Scripts\python.exe -m pytest backend\tests -v --cov=backend/app --cov-report=term-missing
  ```

- **Exact next action:** Strengthen the Phase 9 PostgreSQL integration test to kill a child process at HITL, resume in a new process after a PostgreSQL container restart, and run the golden set against PostgreSQL; then rerun the gates before proceeding to Phase 10.
- **Open risks:** The master prompt and live-data addendum are missing, so their exact requirements cannot be validated. External/sanctions semantics remain assumptions in ADR-009. Tesseract, Ollama, Redis CLI, and PostgreSQL CLI are unavailable on PATH; Redis/PostgreSQL are available through Docker Compose.
