# EcoChain Copilot: Enterprise Multi-Agent Supply Chain Intelligence

## 1. The Enterprise Problem Statement

### Manual compliance auditing does not scale

Large apparel and consumer-goods brands source from hundreds of factories across dozens of jurisdictions. Each supplier relationship generates a continuous stream of unstructured evidence: scanned certificates, Bills of Materials (BOMs), chemical test reports, invoices, and multi-year audit histories. Compliance officers verify claims such as "100% organic cotton" or "zero restricted substances" by reading these documents by hand.

This process fails on four fronts:

- **Throughput.** Review capacity grows linearly with headcount, while the document volume and the number of regulated claims grow faster with every new regulation.
- **Consistency.** Two reviewers reading the same scanned certificate reach different conclusions. Expired validity dates, mismatched scopes, and issuer inconsistencies are missed under volume pressure.
- **Latency.** Verification happens after purchase orders are placed. Risk is discovered when it is already inside the supply chain.
- **Reactivity.** Audit history is read as a record, not used as a signal. Nobody forecasts which factory is likely to fail its next audit.

### The legal exposure is direct

The EU Corporate Sustainability Due Diligence Directive (CSDDD) obliges in-scope companies to identify, prevent, and remediate adverse environmental and human-rights impacts across their value chains, and to evidence that they did so. Alongside it, EU anti-greenwashing rules and consumer-protection enforcement make unsubstantiated sustainability claims a source of penalties, litigation, and reputational damage. The burden is on the brand to produce evidence, not on the regulator to disprove the claim. A compliance process that cannot show which document, on which page, under which version of which law supported a decision is not defensible.

### Naive LLM automation introduces new failure modes

Pointing a general-purpose LLM at a folder of supplier PDFs trades one risk for three:

1. **Hallucinated compliance.** An LLM that asserts a certificate is valid, or cites a regulation article that does not say what it claims, creates a false record of due diligence. In a regulated context, a confident wrong answer is worse than no answer.
2. **Data leakage.** Supplier documents contain commercially sensitive pricing, contract terms, bank details, and personal data of workers and signatories. Sending raw pages to a third-party API puts that data outside the enterprise trust boundary and may breach GDPR and contractual confidentiality obligations.
3. **No audit trail.** If the model, prompt, document, and law version behind a decision are not recorded, the decision cannot be reproduced, explained, or defended to a regulator.

EcoChain Copilot is designed around these constraints. It automates evidence gathering and analysis while keeping decisions deterministic, data local, and every output traceable.

---

## 2. The Solution & Architecture

EcoChain Copilot is a multi-agent system in which language models explain and deterministic code decides. Four design principles govern the architecture.

### 2.1 Deterministic verification over generative judgment

Compliance outcomes are never produced by an LLM. A dedicated **Verifier** node applies rule-based checks to structured extraction output:

- certificate validity window against the assessment date
- issuer match against an approved issuer registry
- certificate scope match against BOM line items and facility identity
- cross-document consistency (conflicting claims, missing pages, mismatched supplier IDs)

The LLM receives the Verifier's verdicts and evidence and writes the human-readable explanation. It cannot overrule a failed check.

### 2.2 Provenance on every claim

Each scorecard line is backed by a typed `Claim` record:

```
Claim {
  claim_text, doc_id, doc_hash, page, bbox,
  extractor_confidence, evidence_ids[],
  regulation_id, regulation_version
}
```

Bounding boxes are carried from layout extraction through to the dashboard, so any scorecard row opens the source page with the supporting region highlighted. Retrieval over the regulation corpus is filtered by `effective_from` and `superseded_by` metadata, so a decision made on a given date cites the law in force on that date. A claim with no evidence ID is not rendered.

### 2.3 A local privacy boundary

All processing that touches raw documents runs inside the enterprise boundary:

1. OCR and layout extraction run locally with LayoutLMv3.
2. PII and commercial data are redacted in two passes: deterministic detection with Microsoft Presidio and custom regex recognizers, followed by a quantized Llama 3 pass as a second-line checker.
3. Entities are replaced with reversible pseudonyms (for example `SUPPLIER_017`, `PRICE_BAND_B`) held in a local token vault.

Only redacted text reaches cloud LLMs. Raw page images never leave the boundary. Pseudonyms are re-hydrated locally when the scorecard is rendered. A leakage test seeds documents with synthetic PII and fails the build if any seeded value appears in an outbound payload.

### 2.4 Predictive risk that changes system behavior

A PyTorch LSTM forecasts each factory's six-month probability of audit failure from historical audit sequences. The model is evaluated against logistic regression and XGBoost baselines on AUROC and Brier score, and is promoted only if it justifies its added complexity. Its calibrated output feeds the graph's routing logic. A high-risk factory lowers the auto-approval confidence threshold, forces additional verification, and adds a re-audit recommendation to the scorecard. The forecast is a control input, not a decoration.

### 2.5 Hybrid query routing

A lightweight classifier routes incoming requests between retrieval-only answers, full document-analysis workflows, and out-of-scope queries, avoiding LLM calls where a cheaper path is sufficient. It is accepted only if it beats an embedding-plus-logistic-regression baseline on routing accuracy, and its savings are tracked as measured cost and latency deltas against an always-LLM configuration.

### 2.6 Human-in-the-Loop as a terminal state

Escalation is triggered by explicit rules (expired certificate, missing page, conflicting evidence, failed entailment check) and by calibrated confidence thresholds. Escalated runs pause on a persistent checkpoint and resume with the reviewer's decision, which is itself recorded in the audit log.

### 2.7 System context

```
 Next.js UI  <--SSE--  FastAPI API  --enqueue-->  Celery/Arq workers  (Redis)
                          |                              |
                          |                      LangGraph runtime
                          |                    (Postgres checkpointer)
                          |                              |
        ---------------- LOCAL PRIVACY BOUNDARY ----------------
        LayoutLMv3 OCR -> Presidio + quantized Llama 3 -> token vault
        ChromaDB (versioned regulations) | Verifier | LSTM risk model
        ------------------------------------------------------------
                                   | redacted text only
                              Cloud LLM (Gemini)
                                   |
              Append-only audit log  |  LangSmith traces & cost
```

---

## 3. The Multi-Agent Workflow

Each agent has a single responsibility and communicates exclusively through typed graph state.

| Agent | Responsibility | Decides? |
|---|---|---|
| **Orchestrator** | Routes requests, enforces step budgets and recursion limits, applies escalation rules, assembles the final scorecard. Reads the risk forecast to adjust thresholds. | Routing and escalation (rule-based) |
| **Redaction Agent** (local) | Runs local OCR and layout extraction, then two-pass PII and pricing redaction with reversible pseudonymization. Emits redacted text with page and bbox mappings. | No |
| **Document Extraction Agent** | Converts redacted documents into structured fields (certificate type, issuer, validity dates, scope, BOM lines) with page, bbox, and confidence for each field. | No |
| **Compliance RAG Agent** | Retrieves applicable regulation passages using hybrid BM25 and dense retrieval with reranking, filtered by jurisdiction and effective date. Returns passages with article-level citations and version IDs. Verifies that each citation entails the claim it supports. | No |
| **Predictive Risk Agent** | Runs the PyTorch LSTM on the factory's audit history and returns a calibrated six-month failure probability with a baseline-comparison tag. | Supplies a control signal |
| **Deterministic Verifier** | Applies rule-based checks (expiry, issuer registry, scope-to-BOM match, cross-document consistency) and returns pass, fail, or escalate for each claim. | **Yes** |

### Execution flow

1. **Ingest.** A user uploads documents. The API stores them, computes document hashes, and enqueues a job, returning a `job_id`.
2. **Route.** The intent router classifies the request. Simple retrieval queries bypass the full pipeline.
3. **Redact.** The Redaction Agent processes documents locally and produces redacted text with provenance maps.
4. **Extract.** The Extraction Agent produces structured, bbox-grounded fields.
5. **Forecast.** The Predictive Risk Agent scores the factory. The result adjusts the escalation threshold for this run.
6. **Retrieve.** The Compliance RAG Agent fetches version-filtered regulation passages and validates citation entailment.
7. **Verify.** The Verifier evaluates every claim against deterministic rules.
8. **Decide.** The Orchestrator applies escalation rules. A claim that fails a rule, falls below the risk-adjusted confidence threshold, or has conflicting evidence moves to a terminal HITL state. The graph checkpoints to Postgres and waits.
9. **Explain and publish.** The LLM drafts explanations from verified results only. The scorecard is rendered with page-level provenance, pseudonyms re-hydrated locally.
10. **Record.** The audit log and LangSmith trace are finalized.

### Safety controls in the graph

- **Typed state with append-only reducers** for claims and evidence, so earlier findings cannot be overwritten by later nodes.
- **Explicit `recursion_limit`** and a per-node retry cap, with a terminal escalate-to-human edge when either is reached.
- **Interrupt and resume** by `thread_id`, so a process restart or redeploy does not lose pending reviews.

---

## 4. The Complete Technology Stack

### Frontend & Streaming

| Component | Role |
|---|---|
| Next.js (React) + TypeScript | Dashboard application |
| Tailwind CSS + `shadcn/ui` | Data tables, risk gauges, review queue, layout |
| Server-Sent Events (SSE) | One-way live stream of agent steps and reasoning summaries, with `Last-Event-ID` reconnect handling |
| PDF viewer with bbox overlay | Renders source pages with the claim's supporting region highlighted |

### Backend & Async Workers

| Component | Role |
|---|---|
| FastAPI | Async API for uploads, job status, SSE endpoints, and review actions |
| Celery or Arq + Redis | Executes long-running graph jobs outside the request cycle and publishes step events to a pub/sub channel consumed by the SSE endpoint |
| Pydantic | Request, response, and state schema validation |
| Docker | Containerization of API, workers, and local-model services |

### Multi-Agent Orchestration

| Component | Role |
|---|---|
| LangGraph | State-machine orchestration with conditional edges and HITL interrupts |
| Typed state (`TypedDict` / Pydantic) with reducers | Append-only evidence and claim accumulation |
| Postgres checkpointer | Durable checkpoints and resumable runs by `thread_id` |
| `recursion_limit` and retry caps | Bounded execution with terminal escalation |
| LangChain | Document loaders and API wrappers |

### Classical ML & Routing

| Component | Role |
|---|---|
| PyTorch LSTM | Six-month audit-failure forecast from historical audit sequences |
| XGBoost and Logistic Regression | Mandatory baselines for the forecaster; the LSTM is promoted only if it outperforms them on AUROC and Brier score |
| Probability calibration (Platt / isotonic) | Ensures the forecast is usable as a threshold-driving control signal |
| Intent router (TensorFlow/Keras DNN, benchmarked against sentence-embedding + Logistic Regression) | Routes requests by cost tier; retained only if it beats the baseline on accuracy and measured cost savings |

### Generative AI & Vision

| Component | Role |
|---|---|
| Gemini API (pinned model version, behind a provider-agnostic interface) | Reasoning, explanation drafting, and entailment checks on redacted text only |
| LayoutLMv3 | Layout-aware field extraction with bounding boxes, fine-tuned on annotated certificates and BOMs |
| Evaluation-judge model from a different family than the generator | Independent scoring for faithfulness |

### Local Privacy & Security

| Component | Role |
|---|---|
| LayoutLMv3 + local OCR (PaddleOCR / Tesseract) | OCR and layout extraction inside the trust boundary |
| Microsoft Presidio + custom regex recognizers | Deterministic first-pass detection of PII, prices, IBANs, emails, and supplier identifiers |
| Quantized Llama 3 8B (llama.cpp / Ollama) | Second-pass redaction checker |
| Local token vault | Reversible pseudonym mapping, re-hydrated locally |
| Auth, per-tenant isolation, rate limiting | Access control for multi-tenant use |
| Leakage test suite | Seeds synthetic PII and asserts nothing appears in outbound cloud payloads |

### Data & Vector Retrieval

| Component | Role |
|---|---|
| ChromaDB | Vector store for regulations and guidelines |
| Sentence-Transformers | Dense embeddings; chunking by legal structure (article, recital, annex) rather than fixed windows |
| BM25 + cross-encoder reranker | Hybrid retrieval and reranking for dense legal text |
| Regulation metadata schema | `jurisdiction`, `effective_from`, `superseded_by`, `version_id`, filtered at query time |
| PostgreSQL | Application data, checkpoints, and the audit log |
| Issuer registry | Approved certificate issuers used by the Verifier (mock registry for demonstration) |

### MLOps & Evaluation

| Component | Role |
|---|---|
| Golden evaluation set (100-200 labeled cases, including forged, expired, scope-mismatched, and conflicting-evidence documents) | Ground truth for regression testing |
| Ragas | Faithfulness and answer relevance, judged by a separate model family |
| Extraction F1 per field | Measures LayoutLMv3 and extraction quality |
| LSTM Brier score and AUROC | Measures forecast quality and calibration against baselines |
| Citation precision and recall; HITL escalation precision and recall; router accuracy | Additional quality gates |
| CI/CD gates (GitHub Actions) | Pull requests fail if Ragas faithfulness, extraction F1, or LSTM Brier score regress past defined thresholds |
| LangSmith | Execution tracing, latency, token usage, and per-document cost tracking |
| Append-only audit log | Records document hash, law version, model version, prompt version, verifier verdicts, and reviewer decisions for each output |
| Deployment: Vercel (frontend), Render/Railway or a self-hosted worker pool (API and privacy tier) | Hosting. Components that handle raw documents run on infrastructure inside the trust boundary |

---

## Known Limitations

- The LSTM's usefulness depends on the availability of real audit histories. If the training data is synthetic, reported metrics describe generator fidelity, not real-world audit risk, and this is stated in the evaluation report.
- The issuer registry is mocked in the reference implementation. A production deployment requires integration with certification-body registries.
- Redaction reduces but does not eliminate leakage risk. The leakage test suite measures it on known patterns; novel formats require ongoing recognizer maintenance.
- Regulation corpora must be curated and versioned manually, or via a controlled ingestion pipeline, as legal text changes.
