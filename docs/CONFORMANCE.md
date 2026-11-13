# Specification conformance audit

Audit scope: Phases 1-10, Master Prompt sections 5-8, Addendum A2 retrofits R1-R4,
and acceptance checklist items 1-20. Status reflects the checked-in implementation and
available test/report evidence, not intended behavior. `partial` means a related
implementation exists but misses a stated requirement or lacks required evidence.

| Requirement | Status | Evidence |
|---|---|---|
| Phase 1: configuration, structured PII-safe logging, typed errors | met | `backend/app/core/`; `backend/tests/unit/` |
| Phase 1: domain contracts and normalized bounding-box validation | met | `backend/app/domain/models.py`; `backend/tests/unit/test_domain_models.py` |
| Phase 1: required DB entities and migrations | met | `backend/app/db/models.py`; `backend/app/db/alembic/versions/` |
| Phase 1: audit chain stores provenance and detects tampering | met | `backend/app/db/audit_log.py`; `backend/tests/unit/test_audit_chain.py` |
| Phase 1: audit rows are append-only at DB level | partial | Migration `2026_11_02_0004` adds PostgreSQL/SQLite triggers and the SQLite unit test blocks raw SQL; PostgreSQL migration verification is pending (`backend/app/db/alembic/versions/2026_11_02_0004_audit_append_only.py`; `backend/tests/unit/test_audit_chain.py`) |
| Phase 1: claims without evidence are rejected before verification/rendering | met | `backend/app/verifier/engine.py`; `backend/tests/unit/test_verifier_rules.py` |
| Phase 2: reproducible manifest and 150-case labeled golden set | met | `scripts/generate_synthetic_data.py`; `data/MANIFEST.json`; `data/golden/golden_set.json` |
| Phase 2: 400+ factories with 36-month histories and factory splits | met | `scripts/generate_audit_histories.py`; `data/MANIFEST.json` |
| Phase 2: hundreds of annotated PDFs with required document diversity/adversarial variants | partial | Generator creates 180 PDFs; scan noise, skew, stamps/signatures and all requested document types are not evidenced (`scripts/generate_documents.py`; `docs/PROGRESS.md`) |
| Phase 2: versioned regulations include a superseded version | met | `data/regulations/csddd_regulations.json`; RAG date-filter tests |
| Phase 2: mock issuer registry clearly labeled | met | `data/registry/approved_issuers.csv`; `backend/app/verifier/registry.py` |
| Phase 3: OCR returns word boxes in normalized space | partial | PyMuPDF text/word extraction exists; Tesseract and scanned-document OCR are not wired (`backend/app/privacy/ocr.py`) |
| Phase 3: Presidio/custom recognizers, reversible tenant vault, redaction report | met | `backend/app/privacy/`; `config/recognizers.yaml`; `reports/redaction.json` |
| Phase 3: Ollama second-pass fails closed when enabled/unavailable | met | `backend/app/privacy/llama_checker.py`; privacy checker tests |
| Phase 3: every external network call is guarded and network imports are confined | met | Ollama, Gemini entailment/answer generation, and OpenAI Ragas judging are isolated under `integrations/` and guarded before transmission; import-boundary and provider guard tests pass (`backend/app/integrations/`; `backend/tests/leakage/test_privacy_leakage.py`; `backend/tests/unit/test_privacy_boundary.py`; `backend/tests/unit/test_rag.py`) |
| Phase 3: seeded values never leak; entity recall is reported | partial | Report covers synthetic redaction/outbound payloads, but not every external-call path (`reports/redaction.json`; `backend/tests/leakage/test_privacy_leakage.py`) |
| Phase 4: extractor interface, heuristic fallback, normalizers | met | `backend/app/extraction/base.py`; `backend/app/extraction/heuristic.py`; `backend/app/extraction/normalizers.py` |
| Phase 4: actual LayoutLMv3 fine-tuning, resume, and model inference | missing | Trainer is evaluation-only and adapter always calls heuristic (`ml/train_layoutlm.py`; `backend/app/extraction/layoutlmv3.py`) |
| Phase 4: per-field F1 and bounding-box IoU evidence | partial | Report exists, but evaluation uses heuristic output and substitutes IoU `0.85` when no IoU is measured (`reports/extraction.json`; `ml/train_layoutlm.py`) |
| Phase 5: legal-structure chunking, parent linkage, and regulation provenance | met | `backend/app/rag/chunker.py`; `backend/app/rag/store.py`; `backend/tests/unit/test_rag.py` |
| Phase 5: Chroma metadata/date/jurisdiction filtering | met | `backend/app/rag/store.py`; date-filter tests |
| Phase 5: BM25+dense hybrid retrieval with reciprocal-rank fusion | met | `backend/app/rag/retriever.py`; RAG unit tests |
| Phase 5: real cross-encoder reranking | met | `backend/app/rag/retriever.py`; `scripts/evaluate_rag.py`; locally executed reranker report in `reports/rag.json` |
| Phase 5: LLM entailment through guard, failure escalates | met | `backend/app/integrations/gemini_entailment.py`; fail-closed checker and guarded-call tests (`backend/app/rag/entailment_checker.py`; `backend/tests/unit/test_rag.py`) |
| Phase 5: >=60-query golden retrieval set, citation/Ragas evaluation | partial | Offline citation, date-filter, answerability, and four-mode ablation gates pass; Ragas faithfulness/answer relevance are `not_run` because API keys are unavailable. Answerability threshold was selected on the same set, not a held-out estimate (`data/golden/rag_golden_set.json`; `data/golden/rag_no_support_set.json`; `reports/rag.json`) |
| Phase 5 / R3: version-aware idempotent ingestion, human proposal/approval, audit decision | met | Source/version-scoped upsert, persisted approval, and audit-chain tests (`backend/app/rag/ingestion.py`; `backend/tests/unit/test_rag.py`) |
| Phase 6: 11 Master Verifier rules and deterministic engine | met | `backend/app/verifier/engine.py`; `backend/tests/unit/test_verifier_rules.py`; `reports/verifier.json` |
| Phase 6 / A3: V-EXT-001/002/003/900 and V-SANC-001/002 semantics | met | Corrected not-found escalation, country/name band, parent-company, stale-source, exact-ID, and name-only/fuzzy outcomes are covered (`backend/app/verifier/rules/`; `backend/tests/unit/test_verifier_rules.py`) |
| Phase 6: registry loader announces MOCK data; critical/normal priorities | met | `backend/app/verifier/registry.py`; `backend/app/verifier/engine.py`; verifier tests |
| Phase 7: train-only normalization, factory/time leakage controls, three-model comparison | met | `ml/train_risk.py`; `reports/risk.json`; risk tests |
| Phase 7: validation-only calibration and reliability evidence | met | `ml/train_risk.py`; `reports/risk.json` |
| Phase 7: 95% CIs and explicit validation promotion rule | met | `backend/app/risk/promotion.py`; `reports/risk.json`; promotion tests |
| Phase 8: DNN-vs-baseline benchmark and promotion decision | met | `ml/train_router.py`; `reports/router.json`; ADR-011 in `docs/DECISIONS.md` |
| Phase 9: bounded graph stages, evidence-backed verdicts, decision and escalation | met | `backend/app/graph/workflow.py`; `backend/tests/e2e/test_graph_workflow.py` |
| Phase 9 / A4: enrich stage performs local snapshot matching and emits external evidence | met | `backend/app/graph/services.py`; snapshot provenance asserted in `backend/tests/integration/test_api_postgres_redis.py`; unavailable data escalates |
| Phase 9: HITL survives process and PostgreSQL restart; audit chain persists | met | `backend/tests/integration/test_graph_postgres_resume.py`; `docs/graph.md` |
| Phase 10: JWT, tenant-scoped repositories, upload checks, idempotency, rate limits | met | `backend/app/api/`; `backend/app/api/repositories.py`; API integration tests |
| Phase 10: Redis Stream SSE supports `Last-Event-ID` replay | met | `backend/app/api/`; `backend/tests/integration/test_api_postgres_redis.py` |
| Phase 10: scorecard endpoint, rendered-page endpoint, query endpoint, factory risk endpoint | met | `backend/app/api/router.py`; tenant, page/ETag, query, and risk tests in `backend/tests/integration/test_api_postgres_redis.py` |
| Phase 10: graph factory and full API job/HITL integration | met | Local fake-backed `create_workflow_services`; real Celery worker pauses and resumes through the API in `backend/tests/integration/test_api_postgres_redis.py` |
| Phase 10 / A5: `/v1/integrations/status` and proposal approve/reject API | met | `backend/app/api/router.py`; tenant setting and proposal decision assertions in `backend/tests/integration/test_api_postgres_redis.py` |
| Section 5: `EvidenceItem` external kinds and `ExternalRef` validation | met | External kinds validate required `ExternalRef` fields (`backend/app/domain/models.py`; `backend/tests/unit/test_domain_models.py`) |
| Section 5: `GraphState` contract and append-only reducers | met | `backend/app/domain/models.py`; `backend/app/graph/workflow.py` |
| R1: external source/snapshot/record/watchlist/proposal tables | met | `backend/app/db/alembic/versions/2026_11_02_0002_addendum_a_tables.py`; DB models |
| R1: required external audit event types and write paths | partial | Generic audit event type is supported; dedicated event writes for every listed operation are not evidenced (`backend/app/db/audit_log.py`; integration/ingestion modules) |
| R2: tenant opt-in, provider field allowlists, payload size limit | met | `backend/app/privacy/outbound_guard.py`; privacy tests |
| R2: guard is sole door to all external calls; no exception paths | met | Runtime Ollama/Gemini calls verify before send; OpenAI's HTTP request hook validates every Ragas judge request; provider guard tests pass |
| R3: corpus never changes autonomously; human approval recorded | met | Version-scoped idempotent upsert is reached through persisted approval with an audit decision; tests prove pending proposals do not ingest (`backend/app/rag/ingestion.py`; `backend/tests/unit/test_rag.py`) |
| R4: external evidence refs require source/fetched_at/snapshot_hash/record_key | met | Pydantic validates required keys and datetime values for all three external evidence kinds |
| Acceptance 1: full Docker stack and golden-case demo | missing | Current compose is infra-only; no full-stack demo evidence (`docker/compose.dev.yml`; `docs/HANDOFF.md`) |
| Acceptance 2: zero seeded outbound leakage and per-entity recall | partial | Synthetic redaction report/test exists; external network paths are not covered |
| Acceptance 3: all cloud LLM calls use outbound guard | met | Gemini entailment/answer and OpenAI Ragas adapters guard their requests (`backend/app/integrations/`; provider tests) |
| Acceptance 4: deterministic Verifier unaffected by adversarial LLM output | partial | Pure deterministic rules exist; explicit prompt-injection invariance gate is not evidenced |
| Acceptance 5: every scorecard line has evidence, hash, page/bbox, regulation version | partial | Domain fields and workflow evidence links exist; explicit rendered-scorecard completeness gate/API absent |
| Acceptance 6: no superseded law cited after its effective date | met | `backend/app/rag/store.py`; date-filter tests |
| Acceptance 7: HITL restart/resume and reviewer audit | met | PostgreSQL process-restart integration test |
| Acceptance 8: hash chain verifies and tampering is detected | met | `backend/app/db/audit_log.py`; `backend/tests/unit/test_audit_chain.py` |
| Acceptance 9: risk baselines/LSTM, CIs, promotion, calibration | met | `reports/risk.json`; `backend/app/risk/promotion.py` |
| Acceptance 10: router baseline benchmark and decision documented | met | `reports/router.json`; ADR-011 |
| Acceptance 11: CI evaluation regression gate and reports regenerate | missing | `eval-gate.yml` / threshold-driven report regeneration not evidenced |
| Acceptance 12: cross-tenant denial, upload abuse, rate limiting | met | `backend/tests/integration/test_api_postgres_redis.py` |
| Phase 11: frontend auth, tenant-scoped jobs, scorecard, reviews, factory risk, audit, integrations, regulation approvals | partial | Implemented under `frontend/src/`; lint/typecheck/unit/build pass; Playwright and backend-service flows remain unverified |
| Acceptance 13: frontend bbox source viewer and SSE reconnect | partial | Authenticated same-origin SSE proxy and evidence bbox viewer implemented; 7 frontend unit tests pass; Playwright browser missing (`frontend/src/`) |
| Acceptance 14: Known Limitations across required docs | partial | Some limits recorded; final README/runbook/security/model cards/evaluation report are not complete |
| Acceptance 15: no external call bypasses guard; seeded PII excluded | met | Import-boundary and guarded Ollama payload tests; live provider adapters are not yet implemented |
| Acceptance 16: external scorecard facts show source/as-of and replay from audit/snapshot hash | partial | Snapshot provenance schema exists; no complete live lookup-to-scorecard evidence |
| Acceptance 17: sanctions exact match fail+critical; fuzzy/outage escalate | met | V-SANC tests and V-EXT-900 tests |
| Acceptance 18: regulation changes require recorded human approval | met | Persisted approval/rejection API and audit-chain integration assertions (`backend/app/api/router.py`; `backend/app/rag/ingestion.py`; `backend/tests/integration/test_api_postgres_redis.py`) |
| Acceptance 19: provider terms/endpoints documented from official docs with check date | partial | ADR-007 documents sources; no complete current verification record for all providers |
| Acceptance 20: external-data limitations documented and no LSTM contamination | partial | ADR-007 records snapshot-first/no-LSTM decision; final Known Limitations docs absent |

## Highest-priority gaps

1. Phase 5 offline gate is closed; semantic Ragas faithfulness/answer relevance remain `not_run` until `GOOGLE_API_KEY` and `OPENAI_API_KEY` are available and the guarded command in `docs/RUNBOOK.md` is explicitly run.
2. Verify migration `2026_11_02_0004` directly against PostgreSQL; the previous SQLite-only check could not exercise the PostgreSQL triggers.
3. Close Phase 4 with actual LayoutLMv3 fine-tuning/inference and an honest held-out evaluation.
4. Expand Phase 2's document corpus to the specified hundreds and add the missing visual/adversarial variation.

This audit is updated as fixes land and reports the current conformance evidence. Phase 10
closed with the real-service gate on 2026-11-03; ADR-019 records the fake-backed local
workflow and synthetic-risk limitations. The all-revisions SQLite smoke test is currently blocked by
pre-existing migration `2026_11_02_0003_api_submissions.py`, which uses SQLite-unsupported
`ALTER COLUMN ... DROP DEFAULT`; the new trigger migration therefore still needs a PostgreSQL
service-backed check.

The current downloaded checkout has no Git metadata, Docker, or configured PostgreSQL/Redis
integration services. Its local frontend checks pass, but Chromium is not installed, so
Playwright E2E remains unverified. These current-checkout limitations are recorded in
`docs/PROGRESS.md` and `docs/HANDOFF.md`; the historical service-backed gate above must not
be treated as a fresh result for this environment.
