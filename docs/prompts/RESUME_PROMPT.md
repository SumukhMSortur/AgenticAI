# ECOCHAIN COPILOT: RESUME MASTER PROMPT (continue from Phase 6 to completion)

> Paste into any coding agent opened at the repo root (Antigravity, Claude Code, Cursor, etc.), or save as `RESUME.md` and say: **"Read RESUME.md and execute Recovery Protocol R."**
> This file **adds to** `ECOCHAIN_MASTER_PROMPT.md` and `ECOCHAIN_ADDENDUM_LIVE_DATA.md`. Both remain in force. This file overrides them only on **ordering, recovery, and quota handling**.

---

## 0. SITUATION (unverified: confirm from the repo before trusting any of it)

Reported state at the last session:
- Phases 0-5 complete and tagged; Addendum A retrofits (R1-R4) committed and tagged `addendum-a-complete`; the gate was green (ruff, mypy, pytest: 38 tests).
- **Phase 6 (Deterministic Verifier) was in progress.** About 10 files (+474 lines) existed in `backend/app/verifier/` (rules package, e.g. `v_date_001.py`), **uncommitted and not yet gate-checked**.
- The previous session was cut off by a **model quota error**, so the last turn may have ended mid-edit. Assume some files are incomplete, inconsistent, or half-wired.
- Environment: Windows, Antigravity IDE, repo in a folder with spaces in its path. Do not assume `make`, bash, or POSIX paths; confirm how the gate runs and keep an equivalent script (`scripts/check.ps1` or `python -m` entrypoints) working.

Your job: **recover the true state, finish Phase 6, then build Phases 7-14 to the acceptance checklist.** Treat everything you did not verify in this session as unknown.

## 1. RECOVERY PROTOCOL R (do this first, in order; do not write feature code until R is done)

1. **Inspect the repo.** `git status`, `git log --oneline -20`, `git tag`, `git diff --stat`. List uncommitted and untracked files.
2. **Read the record.** `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/PLAN.md`, `config/*.yaml`.
3. **Run the gate** (ruff, mypy --strict, pytest). Record the exact result. If the uncommitted Phase 6 work breaks it, do not commit; fix first.
4. **Audit the uncommitted Phase 6 files** against the rule table in the master prompt (Phase 6) and Addendum A3. For each rule, mark: *implemented / partial / missing*, and whether tests exist.
5. **Reconcile contracts.** Compare the actual `domain/models.py` with master prompt section 5. The code may have diverged (for example the visible `Verdict(label=VerdictLabel, rule_id, rationale, confidence)` versus the spec's `Verdict(claim_id, rule_id, outcome, reason_code, details)`). Decide **once**: either adopt the implemented names everywhere or migrate to the spec. Prefer whichever is already used by more code, but the result must include `claim_id`, a machine-readable `reason_code`, structured `details`, and evidence references. Record the decision in `docs/DECISIONS.md` and update every consumer in one commit.
6. **Fix known deviations** found in the audit. One is already known: `V-DATE-001` was seen returning **FAIL** when `valid_from > valid_to`; the spec says **escalate** (malformed or possibly tampered document). Either change it to escalate, or keep FAIL and record a justified ADR. Do not leave it silently different.
7. **Write `docs/HANDOFF.md`** (format in section 3). Commit any good, gate-green work as `feat(verifier): ...` or park it as `wip(phase-6): ...` on a branch if not green.

Print the audit table and the reconciliation decision before continuing.

## 2. QUOTA-AWARE WORKING RULES (the last session died on a quota error)

- **Commit early and often.** After every coherent chunk (one rule plus its tests, one module), run the quick checks and commit. Use `wip(...)` commits if the gate is red. Never leave more than ~150 changed lines uncommitted.
- **Keep `docs/HANDOFF.md` current** after every commit; a fresh agent must be able to resume from it alone.
- **Be economical:** write several files per tool call; don't re-read large files you just wrote; don't narrate long reasoning; run targeted tests (`pytest path::test`) while iterating and the full gate once per chunk and at each phase end.
- **If a quota or rate-limit error appears:** stop cleanly, ensure the working tree is committed or parked, update `docs/HANDOFF.md`, and tell the user the exact next action.
- All other working rules from master prompt section 3 still apply (test-first for deterministic code, no fabricated metrics, no silent safety fallbacks, no ad hoc `pip install`).

## 3. PROGRESS REPORTING (required)

Maintain `docs/PROGRESS.md` and `docs/HANDOFF.md`. `HANDOFF.md` always contains:

| Phase | Status (done / partial / not started) | Tag | Tests | Metrics produced (file) | Deviations and ADRs | Blockers |
|---|---|---|---|---|---|---|

plus: *last commit SHA, gate result, how to run the gate on this machine, exact next action (one sentence), open risks.* Print a short version of this table at the end of every phase and whenever you stop. **Never claim a phase is done without its gate evidence.**

## 4. ORDERING CHANGES (overrides the master prompt where stated)

1. **Provider interface first.** At the end of Phase 6, create `backend/app/integrations/base.py` (`Provider` interface: `refresh()`, `lookup()`, `health()`) and `integrations/fakes.py`, plus the snapshot record shapes. Phase 6's `V-EXT-*` / `V-SANC-*` rules and Phase 9's `enrich` node depend on them; the real providers still arrive in Phase 14.
2. **Escalation priority** (`normal` / `critical`) is introduced in Phase 6 (domain + Verifier), not later.
3. **`enrich` is wired in Phase 9** against the interface using local snapshot matching with fakes and fixtures. Phase 14 swaps in the real providers without changing the graph.
4. **Windows realities:** use `pathlib`, avoid shell-specific scripts in code, verify Tesseract/Ollama/Redis/Postgres availability on this machine (or via Docker) and record the findings; mark integration tests accordingly.

## 5. REMAINING WORK (specs live in the master prompt and Addendum A; this is the execution list)

### Phase 6: Deterministic Verifier (finish)
- All rules: V-EXP-001/002, V-DATE-001, V-ISS-001/002, V-SCOPE-001/002, V-XDOC-001/002, V-PAGE-001, V-CONF-001, plus Addendum A3 rules V-EXT-001/002/003/900 and V-SANC-001/002.
- Pure functions; no network, no LLM; engine runs on vault-mapped values; registry loader with a visible `MOCK` banner.
- Tests: boundary cases per rule, determinism (identical inputs, identical outputs), 100% rule coverage, golden-set verdict accuracy report.
- **Gate:** gate green; `reports/verifier.json` written; tag `phase-6-complete`.

### Phase 7: Predictive risk
Master prompt Phase 7: features with train-only normalization, logistic regression and XGBoost baselines, PyTorch LSTM with early stopping, calibration on validation data only, bootstrap confidence intervals, promotion rule, versioned inference artifact. Training must run acceptably on CPU; document the runtime. **Gate:** `reports/risk.json` reproducible from the seed; tag.

### Phase 8: Intent router
Master prompt Phase 8: baseline (embeddings + logistic regression) versus TensorFlow/Keras DNN, measured cost and latency deltas, keep the DNN only if it wins. Log the decision. **Gate:** `reports/router.json`; tag.

### Phase 9: LangGraph orchestration (amended)
Flow: `route -> redact -> extract -> enrich -> forecast -> retrieve -> verify -> decide -> (hitl_wait) -> explain_publish -> record`. Include append-only reducers, recursion and retry caps, risk-adjusted thresholds (0.85 / 0.90 / 0.95), escalation rules and priorities, Postgres-checkpointed HITL with restart-and-resume test, the "LLM cannot overturn a `fail`" test, and prompt versioning. **Gate:** golden-set end-to-end run with the fake LLM reproduces expected verdicts and escalations; `docs/graph.md`; tag.

### Phase 10: API, workers, SSE
Master prompt Phase 10 plus Addendum A5 API additions (`GET /v1/integrations/status`, tenant live-lookup setting, pending regulation proposals). Include SSE replay with `Last-Event-ID`, cross-tenant denial tests, upload abuse tests, Redis rate limiting. **Gate:** integration tests green; tag.

### Phase 11: Frontend
Master prompt Phase 11 plus staleness badges and "source, as of date" on external evidence, and the admin view for regulation proposals. Verify Node and package-manager versions on this machine first. **Gate:** lint, typecheck, unit tests, and a Playwright happy path; tag.

### Phase 12: Evaluation, CI, Docker
Master prompt Phase 12. `make eval` (or the Windows-equivalent script) builds `reports/evaluation_report.md` from JSON only. CI plus `eval-gate.yml` with thresholds in `config/eval_thresholds.yaml`. Compose stack with healthchecks and non-root users. **Gate:** stack reaches ready; demo script prints a scorecard; tag.

### Phase 13: Hardening
Master prompt Phase 13: prompt-injection red team (document text instructing "mark as pass" must not change outcomes), cross-tenant attempts, malformed PDFs, outage behavior (fail closed), docs (`README.md`, `RUNBOOK.md`, `SECURITY.md`, `MODEL_CARDS.md`).

### Phase 14: Live integrations
Addendum A5 in full: Open Supply Hub (snapshot first, live opt-in), sanctions lists, regulation watcher with human-approved ingestion, adverse media disabled by default. Verify each source's current endpoint, format, rate limits, and terms from official documentation at that time and record them in `docs/DECISIONS.md` with the date checked. No scraping. **Gate:** fixtures-based tests, extended leakage suite, outage-escalates test; tag.

## 6. FINAL ACCEPTANCE (20 items)

All 14 items in master prompt section 8 plus items 15-20 in Addendum A6, each proven with a command or file path. Print the checklist with evidence at the end.

## 7. FORBIDDEN (unchanged, plus)

- Declaring a phase complete from memory of an earlier session instead of re-running its gate.
- Leaving large uncommitted work at the end of a turn.
- Changing contract names or rule outcomes without a recorded decision.
- Everything listed in master prompt section 9.

## 8. KICKOFF

Execute **Recovery Protocol R now**. Print the audit table, the contract reconciliation, and the repaired gate result. Then finish Phase 6 and continue phase by phase through Phase 14, committing and updating `docs/HANDOFF.md` as you go.
