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
| 7 Predictive risk | partial (gate passed; provenance-final report pending) | — | 70 tests; risk package 100% statement coverage; CPU training and inference verified | `reports/risk.json` will be regenerated after commit | ADR-010; XGBoost selected because LSTM missed configured AUROC margin | Regenerate report against the implementation commit, then commit/tag |
| 8 Intent router | not started | — | — | — | — | Phase 7 report/provenance commit and tag |
| 9 LangGraph orchestration | not started | — | — | — | Provider/fakes now exist | Master requirements include Postgres-backed restart/resume |
| 10 API, workers, SSE | not started | — | — | — | — | Redis/PostgreSQL/Docker unavailable |
| 11 Frontend | not started | — | — | — | — | Frontend files/package manifest not yet verified |
| 12 Evaluation, CI, Docker | not started | — | — | — | — | Docker unavailable |
| 13 Hardening | not started | — | — | — | — | Service-backed outage tests unavailable |
| 14 Live integrations | not started | — | — | — | ADR-007/009 | Addendum A5 absent; live-provider terms/endpoints must be verified before wiring |

## Current checkpoint

- **Phase 6 implementation commit:** `0a64e25` (`feat(verifier): complete deterministic verification engine`).
- **Phase 6 gate (run from the repository root, Python 3.12.10):** Ruff passed; strict mypy passed across 64 source files; pytest passed (63 passed); verifier package coverage is 100% (397/397 statements). Golden evaluation: 150/150 expected verdicts and 150/150 escalation results; report dataset SHA-256 is `b03022a6d195729e038ba07f311ebc3b846c33125b8943cb75610af86b5a78a3`, seed 42; `data/MANIFEST.json` verifies.
- **Phase 7 implementation gate:** Ruff and strict mypy passed; pytest passed (70 passed); risk package statement coverage is 100% (167/167). Training on CPU completes in about 10.5 seconds; deterministic metrics and artifact hash were reproduced, and the local XGBoost inference artifact loaded successfully. The report must be regenerated after the implementation commit.
- **How to run the gate on Windows PowerShell:**

  ```powershell
  Set-Location "E:\AgenticAI project\AgenticAI"
  .\.venv\Scripts\python.exe -m ruff check backend
  .\.venv\Scripts\python.exe -m mypy --strict backend\app
  .\.venv\Scripts\python.exe -m pytest backend\tests -v --cov=backend/app --cov-report=term-missing
  ```

- **Exact next action:** Commit the gated Phase 7 implementation, regenerate `reports/risk.json` against that commit, and tag Phase 7 before starting the intent-router benchmark.
- **Open risks:** The master prompt is available only as a read-only attachment and `ECOCHAIN_ADDENDUM_LIVE_DATA.md` remains absent; external/sanctions semantics are explicitly recorded as assumptions in ADR-009. Docker, Tesseract, Ollama, Redis CLI, and PostgreSQL CLI are unavailable on this machine.
