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
| 9 LangGraph orchestration | not started | — | — | — | Provider/fakes now exist | Master requirements include Postgres-backed restart/resume |
| 10 API, workers, SSE | not started | — | — | — | — | Redis/PostgreSQL/Docker unavailable |
| 11 Frontend | not started | — | — | — | — | Frontend files/package manifest not yet verified |
| 12 Evaluation, CI, Docker | not started | — | — | — | — | Docker unavailable |
| 13 Hardening | not started | — | — | — | — | Service-backed outage tests unavailable |
| 14 Live integrations | not started | — | — | — | ADR-007/009 | Addendum A5 absent; live-provider terms/endpoints must be verified before wiring |

## Current checkpoint

- **Phase 6 implementation commit:** `0a64e25` (`feat(verifier): complete deterministic verification engine`).
- **Phase 6 gate (run from the repository root, Python 3.12.10):** Ruff passed; strict mypy passed across 64 source files; pytest passed (63 passed); verifier package coverage is 100% (397/397 statements). Golden evaluation: 150/150 expected verdicts and 150/150 escalation results; report dataset SHA-256 is `b03022a6d195729e038ba07f311ebc3b846c33125b8943cb75610af86b5a78a3`, seed 42; `data/MANIFEST.json` verifies.
- **Phase 7 gate:** Ruff and strict mypy passed; pytest passed (70 passed); risk package statement coverage is 100% (167/167). The CPU training run, deterministic metrics/artifact hash, and XGBoost inference were verified.
- **Phase 7 implementation/report:** `bae5771` (`feat(risk): train and evaluate calibrated risk models`); report source SHA matches. Test metrics for served XGBoost: AUROC 1.000, PR-AUC 1.000, Brier 0.000229, ECE 0.006947; all models and 95% bootstrap intervals are in `reports/risk.json`. CPU run: 10.369 seconds; the model artifact SHA is recorded in the report but the artifact is not committed.
- **Phase 8 implementation/report:** `9a9ab50` (`feat(router): add offline intent routing benchmark`); `reports/router.json` source SHA matches. The 144-query set is split 86/29/29 with near-equal per-intent representation. Logistic Regression and the DNN tied at validation/test accuracy 0.9655 and macro-F1 0.9663; the DNN failed the required validation margin and is not retained. Logistic Regression warm CPU p50/p95 latency was 9.81/10.90 ms versus 65.68/67.78 ms for the DNN. The test-set fake-LLM reference counted 1,213 input and 323 output tokens and estimated $0.00037575 at illustrative rates; local token-priced API spend was $0. The report and local artifact SHA were reproduced on a second training run.
- **How to run the gate on Windows PowerShell:**

  ```powershell
  Set-Location "E:\AgenticAI project\AgenticAI"
  .\.venv\Scripts\python.exe -m ruff check backend
  .\.venv\Scripts\python.exe -m mypy --strict backend\app
  .\.venv\Scripts\python.exe -m pytest backend\tests -v --cov=backend/app --cov-report=term-missing
  ```

- **Exact next action:** Begin Phase 9 LangGraph orchestration, then test Postgres-backed HITL restart/resume. Docker and PostgreSQL are not available on this host.
- **Open risks:** The master prompt is available only as a read-only attachment and `ECOCHAIN_ADDENDUM_LIVE_DATA.md` remains absent; external/sanctions semantics are explicitly recorded as assumptions in ADR-009. Docker, Tesseract, Ollama, Redis CLI, and PostgreSQL CLI are unavailable on this machine.
