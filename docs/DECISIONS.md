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
