# Architecture Decisions Record (ADR)

This document tracks all locked design decisions, conflict resolutions, and dependency modifications for **EcoChain Copilot**.

---

## 1. Locked Decisions and Conflict Resolutions

### ADR-001: Frontend Framework (Next.js over Streamlit)
- **Context:** Earlier prototypes considered Python-based rapid UI (Streamlit), while enterprise production mandates high-performance, accessible, and reactive interfaces.
- **Decision:** Locked to Next.js (App Router, TypeScript strict, Tailwind CSS, shadcn/ui).
- **Rationale:** Streamlit cannot deliver complex bounding-box interactive document overlays, responsive data tables, resilient SSE reconnections with `Last-Event-ID`, or production JWT session management without state leaks.

### ADR-002: Live Streaming Protocol (Server-Sent Events only)
- **Context:** Real-time progress updates are required as multi-agent nodes complete tasks.
- **Decision:** SSE only over HTTP with standard `Last-Event-ID` resumption headers. No WebSockets.
- **Rationale:** Agent progress streaming is strictly unidirectional (backend worker -> client browser). SSE works cleanly through enterprise proxies, corporate firewalls, and HTTP/2 multiplexing, whereas WebSockets introduce unnecessary bidirectional state and reconnect fragility.

### ADR-003: Task Queue and Worker Engine (Celery + Redis)
- **Context:** Graph orchestration and OCR/deep-learning inferences are CPU-heavy and cannot block FastAPI's async event loop.
- **Decision:** Celery backed by Redis for task brokering and event stream publication.
- **Rationale:** Celery provides robust worker concurrency, retry policies, task revocation, and seamless integration with Redis streams for live agent telemetry.

### ADR-004: Report Generation Architecture (No Separate Report Agent)
- **Context:** Potential architecture considered a standalone generative "Report Synthesis Agent" that might synthesize findings.
- **Decision:** No autonomous report agent. The LLM acts solely as a drafting tool in `explain_publish`, operating exclusively on verified verdicts and evidence IDs emitted by the Deterministic Verifier.
- **Rationale:** An LLM must never have the authority to decide compliance, override failed checks, or hallucinate findings. The Verifier produces deterministic verdicts; the LLM merely phrases human-readable explanations.

### ADR-005: Privacy Boundary and Verifier Inputs (Vault-Mapped Values)
- **Context:** Redaction replaces sensitive entities (e.g., supplier names, facility IDs) with pseudonyms before text is sent to cloud LLMs.
- **Decision:** The Deterministic Verifier executes strictly *inside the local trust boundary* on real, vault-mapped values, not on pseudonyms.
- **Rationale:** Evaluating compliance rules (e.g., fuzzy-matching certificate issuer names against official certification registries or verifying facility identifiers) requires canonical, real entity strings. Running the Verifier inside the boundary preserves complete data security while allowing accurate rule evaluation.

---

## 2. Dependency Decisions & Additions

### ADR-006: Auth, Dev, and Quality Assurance Tools
- **Context:** The initial lock file lacked authentication libraries (`PyJWT`, `argon2-cffi`) and developer QA tooling (`ruff`, `mypy`, `pytest-cov`, `pre-commit`).
- **Action:** Added `PyJWT`, `argon2-cffi`, `ruff`, `mypy`, `pytest-cov`, and `pre-commit` to `requirements.in`.
- **Recompilation:** Recompiled via `uv pip compile requirements.in --python-version 3.12 --universal --no-annotate -o requirements.txt` and installed into `.venv`.
- **Verification:** All tools tested and validated against Python 3.12.10.

---

## 3. Live External Data Decisions (Addendum A)

### ADR-007: Live External Data Strategy & Architecture
- **Context:** EcoChain Copilot requires external compliance validation (facility directory matching via Open Supply Hub, official sanctions/watchlists from EU/OFAC, and EUR-Lex regulatory changes).
- **Decision:**
  1. **Snapshot-First Local Verification:** External registries and watchlists are ingested into local database snapshots (`external_snapshots`, `external_records`). Lookups occur strictly locally inside the boundary to avoid leaking business supplier relationships.
  2. **Opt-in Live Calls Guarded:** Direct external API calls are tenant opt-in only, governed by `ExternalCallPolicy` in `OutboundGuard` enforcing per-provider field allowlists (e.g. facility name, country only). Raw PII, vault values, pseudonym maps, or images are prohibited from external egress.
  3. **Pure Verifier:** The Deterministic Verifier never initiates network calls; external evidence is fetched upstream by the `enrich` node and supplied as standard `EvidenceItem` inputs.
  4. **Human-in-the-Loop for Regulation Updates:** Regulatory changes detected from official gazettes are stored in `regulation_update_proposals` and require explicit human reviewer authorization before ingestion into the active RAG vector index.
  5. **No LSTM Contamination:** External watchlist and directory matches serve as rule-based escalation/fail triggers and UI context; they are strictly excluded as features in the predictive risk LSTM.
- **Provider Registry & Terms (Verified Build-Time):**
  - **Open Supply Hub (OS Hub):** Default local snapshot. Live endpoint `https://opensupplyhub.org/api/docs/` (`v1/production-locations`), CC-BY-SA 4.0 / ODbL terms, rate-limited and token-authenticated.
  - **EU Consolidated Financial Sanctions (FSF):** XML/CSV bulk snapshot from European External Action Service (EEAS) official portal. Public sector reuse license. Local matching only.
  - **OFAC Consolidated Sanctions (SDN & Non-SDN):** XML/CSV bulk snapshot from U.S. Treasury OFAC official portal. U.S. government public domain. Local matching only.
  - **EUR-Lex Regulatory Feed:** Official EU Publications Office RSS/ATOM feed for CSDDD/ESPR legal acts. Local candidate ingestion via proposal review.

### ADR-008: Canonical Verifier Verdict Contract
- **Context:** The interrupted Phase 6 rule files used `VerdictLabel`, `label`, `rationale`, and `confidence`, but those names were not defined by the domain model. The existing `Verdict` model and domain tests use `claim_id`, `outcome`, `reason_code`, and structured `details`.
- **Decision:** Keep the existing domain contract canonical, add `evidence_ids` to `Verdict`, and migrate every implemented rule to it. Rules require the claim and supporting evidence IDs; rationale and confidence remain structured detail values. Issuer checks receive an already-loaded registry so the rules themselves remain deterministic and perform no I/O.
- **V-DATE-001:** An impossible range (`valid_from > valid_to`) escalates, as required by the recovery prompt; it is not treated as an ordinary compliance failure.
- **Rationale:** This preserves the contract already consumed by the domain and scorecard tests, satisfies the required evidence trace, and avoids maintaining two competing verdict schemas.

### ADR-009: Snapshot-Only External Verification Semantics
- **Context:** External and sanctions rules are deterministic and consume local snapshot evidence; the source Addendum A3 is now present in `docs/prompts/ECOCHAIN_ADDENDUM_LIVE_DATA.md`.
- **Decision:** Match Addendum A3: V-EXT-001 escalates when facility identity is not found; V-EXT-002 escalates on country mismatch or fuzzy name ratios from 0.75 through 0.90; V-EXT-003 escalates on a different or unverified parent company; V-EXT-900 escalates on unavailable or stale sources. Absence is never an automatic failure. V-SANC-001 fails only exact identifier hits at critical priority; V-SANC-002 escalates name-only and fuzzy matches at or above 0.90 at critical priority. Missing external evidence remains fail-closed.
- **Escalation priority:** Critical risk at the configured high-risk threshold or a rule explicitly marked critical yields `critical`; other escalations yield `normal`. Verdict outcomes remain unchanged by this classification.
- **Rationale:** Local snapshot inputs keep the Verifier pure and prevent supplier lookups from causing network egress inside the rule engine.
- **Evidence:** Boundary tests in `backend/tests/unit/test_verifier_rules.py` cover thresholds, missing values, parent-company mismatch, staleness, and critical sanctions outcomes.

### ADR-010: Validation-Only Risk Model Promotion
- **Context:** Phase 7 requires comparable Logistic Regression, XGBoost, and CPU PyTorch LSTM models, validation-only calibration, test confidence intervals, and a versioned served artifact.
- **Decision:** Normalize sequence and engineered features using training-split statistics only. Fit Platt calibrators on the factory-disjoint validation split; select promotion using validation AUROC and Brier score only. Promote the LSTM only when it clears both baselines by configured margins; otherwise serve the validation-best baseline. Keep generated joblib model artifacts local and ignored by Git; the committed report records their SHA-256.
- **Measured outcome:** On the seeded synthetic data, the LSTM did not clear both baseline promotion margins; XGBoost was selected as the served baseline. Test metrics are recorded in `reports/risk.json`.
- **Rationale:** The test split remains reporting-only, model promotion cannot be driven by test-set performance, and trained weights are not committed.
- **Limitation:** Synthetic labels and drift patterns produce unusually strong metrics and cannot establish real-world predictive validity. Retrain locally with the pinned Python environment before inference when the ignored model artifact is absent.

### ADR-011: Offline Intent Router Promotion
- **Context:** Phase 8 requires an intent classifier comparison between a sentence-embedding/Logistic Regression baseline and a TensorFlow/Keras DNN, including quality, latency, and token-priced cost evidence.
- **Decision:** Embed manually authored, stratified queries with `sentence-transformers/all-MiniLM-L6-v2` at pinned revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, loaded from the local cache only. Fit both classifiers on the exact same normalized 384-dimensional embeddings. Promote the DNN only when its validation macro-F1 exceeds Logistic Regression by at least 0.01 and validation accuracy is not lower. Keep the promoted model artifact local and verify its SHA-256 at inference.
- **Measured outcome:** Both models tied on validation (accuracy 0.9655, macro-F1 0.9663); therefore Logistic Regression is served and the DNN artifact is not retained. The test split is reporting-only. Warm single-query CPU latency and an illustrative, token-counted always-LLM fake are recorded in `reports/router.json`.
- **Cost interpretation:** The fake uses fixed illustrative per-token rates, not a vendor quote. The reported 100% reduction is token-priced external API spend only; local compute and non-token costs are excluded.
- **Rationale:** The simpler baseline matches the DNN's measured quality while being substantially faster, and validation-only selection avoids test-set promotion bias.
- **Limitations:** The 144-query hand-authored set is small and cannot establish production intent accuracy. The report's token cost and warm latency are local benchmark estimates. Model card metadata declares Apache-2.0; the model is not vendored into the repository.

### ADR-012: Bounded LangGraph Orchestration and Partial Persistence Gate
- **Context:** Phase 9 requires deterministic verifier decisions, controlled retries, human review, durable checkpointing, and final audit recording.
- **Decision:** Compose the workflow from required injected router/stage/verifier/explainer/audit interfaces. Keep verdict and scorecard decisions deterministic; give the explainer only verified status/findings/reason codes/evidence IDs and risk score. Limit retries to explicitly transient exceptions, cap attempts and graph recursion, and validate human review decisions before resume. Use a PostgreSQL checkpointer for restart durability.
- **Risk behavior:** Recommend re-audit at 0.85, escalate to normal-priority review at 0.90, and critical-priority review at 0.95. Existing verifier escalations take precedence. Review-required status takes precedence over a failing verdict; otherwise failures yield non-compliant.
- **Initial gate outcome:** At the first Phase 9 checkpoint, PostgreSQL was unavailable, so only in-memory interrupt/resume was verified and the phase was marked partial. ADR-014 records the later real-service closure gate.
- **Rationale:** Explicit dependencies and failure boundaries avoid success-shaped fallbacks; minimized explainer input prevents untrusted narrative generation from changing compliance decisions. The partial status makes the missing durability evidence visible rather than inferring it from in-memory behavior.

### ADR-013: Docker Desktop for Local PostgreSQL and Redis
- **Context:** The development and integration workflow requires PostgreSQL 16 and Redis 7, and the host has no local database/cache installations.
- **Decision:** Use Docker Desktop with its WSL2 Linux engine as the supported local runtime. Define version-major-pinned `postgres:16` and `redis:7` development services in `docker/compose.dev.yml`, health-check them, and persist their state in Compose-named volumes. Keep development credentials in ignored `.env`; commit only the explicit development-only placeholders in `.env.example`.
- **Verification:** Docker CLI 29.9.2 and Compose v5.6.1 responded. Both services reached healthy status; migrations applied to both databases, including a full rollback/reapply cycle on `ecochain_test`; Redis returned `PONG`.
- **Rationale:** This gives Windows developers reproducible real services without requiring local PostgreSQL or Redis installs. The test database is separate from application data, and the named-volume reset is explicitly documented as destructive.

### ADR-014: Phase 9 Durable HITL Gate Closure
- **Context:** The original Phase 9 PostgreSQL check exercised saver recreation in one process, which did not prove the required child-process or container-restart recovery behavior.
- **Decision:** Require an integration gate that pauses a workflow in a child process, terminates that process, restarts the local PostgreSQL container, and resumes the same thread in a new process. Verify the resulting scorecard/verdicts, persisted audit row, and audit hash chain. Also run the complete 150-case golden set through PostgreSQL-backed workflow checkpoints and audit recording.
- **Verification:** Both PostgreSQL integration tests pass. The full suite passes (87 passed, zero skipped; 93% app coverage); Ruff and strict mypy pass. The phase is tagged `phase-9-complete`, while `phase-9-partial` remains as the historical checkpoint.
- **Rationale:** This supplies direct evidence of durable checkpoint recovery and real database-backed workflow behavior rather than inferring it from in-memory or same-process tests.

### ADR-015: Enforce audit immutability and external provenance at boundaries
- **Context:** The conformance audit found that ORM listeners could be bypassed by raw SQL and that external `EvidenceItem` kinds accepted incomplete provenance. It also found the local Ollama checker bypassed the outbound-network import boundary.
- **Decision:** Add database-level update/delete triggers with ORM listeners retained as defense in depth; validate `ExternalRef` for every external evidence kind; and place Ollama HTTP under `integrations/`, requiring tenant context and a successful `OutboundGuard` check before transmission.
- **Verification:** Targeted audit/domain/privacy tests and Ruff/strict mypy pass. The SQLite test blocks raw SQL tampering. PostgreSQL verification of migration `2026_11_02_0004` remains pending because Docker Desktop's engine was unavailable.
- **Rationale:** This preserves audit integrity and data minimization without making the deterministic domain or Verifier perform I/O.

### ADR-016: Ragas Dependency Compatibility
- **Context:** Ragas 0.4.3 imports `langchain_community.chat_models.vertexai`, which is absent from `langchain-community` 0.4.2; its import fails with that release.
- **Decision:** Pin `langchain-community==0.3.31` and declare the OpenAI judge dependencies (`openai` and `httpx2`) explicitly. Keep the project's LangChain and LangChain Core versions unchanged.
- **Verification:** Ragas imports successfully under Python 3.12; all 20 RAG unit tests pass; targeted strict mypy and Ruff pass.
- **Rationale:** This is the narrowest compatibility pin that makes the selected Ragas release usable without broad framework upgrades.

### ADR-017: RAG Evaluation Thresholds and External-Call Consent
- **Context:** Phase 5 requires a reproducible golden retrieval set, citation metrics, faithfulness, and answer relevance. Completing the semantic metrics sends evaluation prompts and public regulation excerpts to third-party model providers.
- **Decision:** Require at least 60 labeled queries, precision@5 >= 0.20, recall@5 >= 0.90, faithfulness >= 0.80, and answer relevance >= 0.80. Use a locally cached embedding model and CrossEncoder for retrieval; use guarded Gemini generation and a separately guarded OpenAI judge for Ragas. External evaluation is disabled unless the operator passes `--allow-external-model-calls`; disable Ragas telemetry before constructing the judge.
- **Verification:** Citation-only run passes precision@5 `0.20`, recall@5 `1.00`, and MRR@5 `0.9833` on 60 queries. Ragas semantic metrics remain pending and are not represented as passed.
- **Rationale:** With one relevant expected chunk per query, precision@5 `0.20` requires the relevant result to appear in the top five. Separate-provider judging, explicit consent, and disabled telemetry make the remaining evaluation boundary visible and auditable.

### ADR-018: Close the Phase 5 Offline Gate; Preserve Ragas as Not Run
- **Context:** The local RAG evaluation can measure citation ranking, metadata date filtering, retrieval ablations, and reranker-based answerability without sending prompts to external providers. Google and OpenAI API keys are not available.
- **Decision:** Close the offline Phase 5 gate with a tagged report, while keeping faithfulness and answer relevance explicitly `not_run` with reason `API keys not available`. Use a CrossEncoder maximum-score threshold of `-2.0`; disclose that it was selected by sweeping the same labeled 80-query set, so answerability accuracy is diagnostic rather than an independent holdout estimate. Resume Phase 10 with `LLM_PROVIDER=fake` in non-live tests.
- **Verification:** `reports/rag.json` records 60 supported and 20 no-support queries, no date-filter violations, all four retrieval modes, citation metrics, and no-support/answerability metrics. No Gemini/OpenAI calls were made.
- **Rationale:** The phase can close on reproducible local evidence without fabricating or estimating unavailable semantic metrics. The pending external evaluation remains an explicit open item with its required keys and command documented in the runbook.
