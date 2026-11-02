# EcoChain Copilot: Master Implementation Plan

## 1. Project Overview & Mission
EcoChain Copilot is an enterprise multi-agent supply-chain compliance intelligence system for apparel brands. Language models explain; deterministic code decides. Data remains local, and every output is traceable to specific document pages, bounding boxes, and versioned regulations.

---

## 2. Environment Audit & Findings (Phase 0)

| Tool / Service | Status | Detection / Configuration | Action / Strategy |
|---|---|---|---|
| **Python** | 3.12.10 | Present in `.venv` | Locked to Python 3.12. |
| **Dependencies** | Locked | Pinned in `requirements.txt` via `uv` | Full dependency lock maintained. |
| **Ruff & Mypy** | 0.17.3 / 2.4.1 | Installed in `.venv` | Configured with `mypy --strict` on `backend/app`. |
| **Tesseract OCR** | Not in PATH | Tested via CLI | Provide `IOcrEngine` interface with mock/PyMuPDF fallback for test runs; configure path via `TESSERACT_CMD`. |
| **Redis** | Offline | Tested via CLI | In-memory pub/sub mock for fast unit tests; Redis client for integration and Docker. |
| **PostgreSQL** | Offline | Tested via CLI | In-memory SQLite / mock checkpointer for unit tests; PostgreSQL + psycopg for integration and Docker. |
| **Ollama** | Offline | Tested via CLI | Feature-flagged `LLAMA_REDACTION_ENABLED=false` by default; graceful escalation stub provided. |
| **Gemini LLM** | Pinned config | Dynamic `GEMINI_MODEL` (e.g., `gemini-2.5-flash`) | Provider-agnostic interface with `FakeLLM` double for unit and golden tests. |

---

## 3. Interface List

All components adhere to clean, decoupled abstract interfaces with comprehensive test doubles (fakes/mocks):

1. **`IExtractor` (`extraction/base.py`)**:
   `extract(document: DocumentRef) -> list[ExtractedField]`
   Implementations: `HeuristicExtractor` (working default/baseline), `LayoutLMv3Extractor`.
2. **`ITokenVault` (`privacy/vault.py`)**:
   `tokenize(tenant_id: str, entity_type: str, raw_val: str) -> str`, `detokenize(tenant_id: str, token: str) -> str`
   Implementation: AES-GCM encrypted in-memory and database vault.
3. **`IOutboundGuard` (`privacy/outbound_guard.py`)**:
   `inspect_and_send(payload: str, tenant_id: str) -> str`
   Enforces no raw PII or vault tokens leave trust boundary; logs payload hashes.
4. **`ILLMProvider` (`llm/base.py`)**:
   `generate(prompt: str, system_instruction: str | None) -> str`
   Implementations: `GeminiProvider`, `FakeLLMProvider`.
5. **`IVectorStore` (`rag/store.py`)**:
   `search(query_embedding: list[float], filters: dict, top_k: int) -> list[Passage]`
   Implementation: ChromaDB with metadata filtering (`jurisdiction`, `effective_from`, `superseded_by`).
6. **`IVerifierEngine` (`verifier/engine.py`)**:
   `verify(claims: list[Claim], context: VerificationContext) -> list[Verdict]`
   Deterministic rules engine (expiry, fuzzy issuer registry, scope matching, cross-doc consistency).
7. **`IRiskForecaster` (`risk/inference.py`)**:
   `predict(factory_id: str, history: AuditHistory) -> RiskForecast`
   Implementations: Calibrated PyTorch LSTM, XGBoost baseline, Logistic Regression baseline.
8. **`IIntentRouter` (`router/inference.py`)**:
   `route(query: str) -> RouteDecision`
   Implementations: Embedding + Logistic Regression baseline, Keras DNN.

---

## 4. Phase Breakdown & Acceptance Gates

- **Phase 0: Recon, Plan, Skeleton**
  - Verify environment, create layout, `pyproject.toml`, Makefile, pre-commit, `.env.example`, CI skeleton.
  - *Gate:* `make check` (ruff, mypy strict, pytest) runs green.
- **Phase 1: Foundations**
  - Config (`pydantic-settings`), safe logging, domain models (BBox, ExtractedField, EvidenceItem, Claim, Verdict, RiskForecast, GraphState), DB models, append-only hash-chained audit log with tamper detection.
  - *Gate:* Tamper-detection test passes; migrations valid.
- **Phase 2: Data (Synthetic and Real)**
  - Seeded generators for 400+ factories (36-mo histories), PyMuPDF document generation (clean, noisy, adversarial), EUR-Lex CSDDD regulation ingestion with versions, mock issuer registry, 150 golden-set test cases.
  - *Gate:* Byte-reproducible outputs from seed; `data/MANIFEST.json` generated.
- **Phase 3: Privacy Boundary**
  - OCR integration, Presidio + regex redaction, Llama checker fallback, AES token vault, outbound guard door to cloud LLMs, leakage test suite with zero tolerance.
  - *Gate:* Leakage test suite green; per-entity recall reported in `reports/redaction.json`.
- **Phase 4: Extraction**
  - Base interface, heuristic extractor (working default), LayoutLMv3 fine-tuning script, field normalizers (ISO dates, issuer canonicalization, material taxonomy).
  - *Gate:* Extraction F1 and bbox IoU measured and written to `reports/extraction.json`.
- **Phase 5: Compliance RAG**
  - Legal structure chunking, ChromaDB store with date filtering (`effective_from <= assessment_date`), BM25 + dense hybrid retrieval with reranker, citation entailment checking.
  - *Gate:* Date-filter tests pass (superseded law excluded); citation metrics in `reports/rag.json`.
- **Phase 6: Deterministic Verifier**
  - Pure functions for V-EXP-001/002, V-DATE-001, V-ISS-001/002, V-SCOPE-001/002, V-XDOC-001/002, V-PAGE-001, V-CONF-001. Evaluated on vault-mapped real values.
  - *Gate:* 100% rule coverage in tests; golden-set verdict accuracy reported; determinism test passes.
- **Phase 7: Predictive Risk**
  - Audit history sequence features, LogReg and XGBoost baselines, PyTorch LSTM with Platt/isotonic calibration. Promotion logic strictly requiring beating baselines.
  - *Gate:* Metrics written to `reports/risk.json`; promotion logic verified.
- **Phase 8: Intent Router**
  - Labeled queries, sentence embedding + LogReg baseline, DNN candidate, benchmark script.
  - *Gate:* Metrics in `reports/router.json`; decision documented.
- **Phase 9: LangGraph Orchestration**
  - State machine with append-only reducers, risk-adjusted escalation thresholds, interrupt/resume checkpointer, explain_publish node with strict outcome preservation.
  - *Gate:* Golden-set end-to-end test passes; graph exported to `docs/graph.md`.
- **Phase 10: API, Workers, Streaming**
  - FastAPI endpoints (tenant-scoped, JWT, rate limited), Celery tasks, Redis stream publisher, SSE endpoint with `Last-Event-ID` resumption.
  - *Gate:* API integration tests, SSE reconnect tests, cross-tenant denial tests pass.
- **Phase 11: Frontend**
  - Next.js + TypeScript strict + Tailwind + shadcn/ui. Source viewer with bounding-box overlay, risk gauge, review queue, SSE live streaming hook.
  - *Gate:* TypeScript strict and frontend tests pass.
- **Phase 12: Evaluation, CI Gates, Packaging**
  - `make eval` generates `reports/evaluation_report.md`. CI gate (`eval-gate.yml`) checks regressions against thresholds. Multi-stage Dockerfile and docker-compose.
  - *Gate:* `docker compose up` brings stack to ready; `make demo` executes golden scenario.
- **Phase 13: Hardening and Final Audit**
  - Red-team prompt injection resilience tests, security audit, RUNBOOK, SECURITY, MODEL_CARDS, README.

---

## 5. Key Risks and Mitigations

1. **Risk:** PII or commercial data leaking to cloud LLMs.
   - *Mitigation:* Single-choke-point `outbound_guard.py` asserting zero vault tokens and zero raw text, enforced by AST/grep testing across codebase.
2. **Risk:** LLM hallucinating or altering verification verdicts.
   - *Mitigation:* Verifier is 100% deterministic code. The graph architecture enforces that `explain_publish` only phrases summaries of already-locked verdicts and drops any claim lacking evidence IDs.
3. **Risk:** Inability to run heavy external services (e.g. Tesseract, live Redis) in restricted environments.
   - *Mitigation:* Decoupled interfaces with robust test fakes and in-memory fallback mechanisms for deterministic development and CI, while full services run in Docker containers.
