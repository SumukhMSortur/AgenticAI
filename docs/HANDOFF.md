# EcoChain Copilot Handoff

| Phase | Status (done / partial / not started) | Tag | Tests | Metrics produced (file) | Deviations and ADRs | Blockers |
|---|---|---|---|---|---|---|
| 0 Recon, plan, skeleton | done | `phase-0-complete` | Current full gate passes | — | Historical record in `docs/PROGRESS.md` | None known |
| 1 Foundations | done | `phase-1-complete` | Current full gate passes | — | Verdict contract reconciliation is ADR-008 | None known |
| 2 Data | done | `phase-2-complete` | Data tests pass | `data/MANIFEST.json` | Generated data is local/ignored | None known |
| 3 Privacy boundary | done | `phase-3-complete` | Leakage tests pass | `reports/redaction.json` | External services unavailable locally | Docker not installed |
| 4 Extraction | done | `phase-4-complete` | Extraction tests pass | `reports/extraction.json` | Historical phase evidence is not fully recorded in `docs/PROGRESS.md` | None known |
| 5 Compliance RAG | partial | `phase-5-complete` | Current RAG tests pass | No `reports/rag.json` found | Tag exists, but phase acceptance evidence is incomplete | RAG report/phase gate evidence |
| 6 Deterministic verifier | partial | — | 12 rule/loader tests; 100% verifier statement coverage; full gate passes | No `reports/verifier.json` | ADR-008; V-DATE-001 invalid range escalates | Eight rule specs, engine, providers/fakes, golden report; master/addendum specs absent |
| 7 Predictive risk | not started | — | — | — | — | Master prompt absent |
| 8 Intent router | not started | — | — | — | — | Master prompt absent |
| 9 LangGraph orchestration | not started | — | — | — | — | Master prompt and provider interface absent |
| 10 API, workers, SSE | not started | — | — | — | — | Master prompt absent; Redis/PostgreSQL/Docker unavailable |
| 11 Frontend | not started | — | — | — | — | Master prompt absent; frontend files not yet verified |
| 12 Evaluation, CI, Docker | not started | — | — | — | — | Master prompt absent; Docker unavailable |
| 13 Hardening | not started | — | — | — | — | Master prompt absent |
| 14 Live integrations | not started | — | — | — | ADR-007 defines snapshot-first and opt-in policy | Addendum A5 absent; Docker/services unavailable |

## Current checkpoint

- **Last existing commit:** `79a09d2` (`feat(addendum-a): integrate live external data strategy into domain, DB, outbound guard, and RAG`)
- **Gate result (run from the repository root):** Ruff passed; mypy passed with no issues across 52 source files; pytest passed (50 tests). Verifier-specific tests report 100% statement coverage (158/158 statements).
- **How to run the gate on Windows PowerShell:**

  ```powershell
  Set-Location "E:\AgenticAI project\AgenticAI"
  .\.venv\Scripts\python.exe -m ruff check backend
  .\.venv\Scripts\python.exe -m mypy backend\app
  .\.venv\Scripts\python.exe -m pytest backend\tests -v --cov=backend/app --cov-report=term-missing
  ```

- **Exact next action:** Restore `ECOCHAIN_MASTER_PROMPT.md` and `ECOCHAIN_ADDENDUM_LIVE_DATA.md` to the repo, then implement the eight missing Phase 6 rules from their tables.
- **Open risks:** The only checked-out implementation requirements for Phases 6–14 are the resume prompt and partial project plan; the two referenced specifications are absent. Do not treat Phase 6 as complete or invent external rule semantics. Docker, Tesseract, Ollama, Redis CLI, and PostgreSQL CLI are unavailable on this machine.
