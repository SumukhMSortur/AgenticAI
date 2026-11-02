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
