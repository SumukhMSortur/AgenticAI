# EcoChain Copilot: Recommended Tech Stack

## Frontend (Microservice 1)
- Next.js (React) + TypeScript
- Tailwind CSS + shadcn/ui (data tables, risk gauges, review queue, sidebar layout)
- Server-Sent Events (SSE) to stream agent steps live, with `Last-Event-ID` reconnect handling
- PDF viewer with bounding-box overlay so each claim opens its source region

## Backend (Microservice 2)
- FastAPI (async) served by Uvicorn
- Python 3.11 or 3.12 in a virtual environment (3.10 is past end-of-life)
- Pydantic for request, response, and state schemas
- Redis + Celery or Arq (choose one) to run long graph jobs and publish step events to the SSE endpoint
- PostgreSQL for application data, LangGraph checkpoints, and the append-only audit log
- Docker for the API, workers, and local-model services

## Multi-agent orchestration
- LangGraph: typed state with append-only reducers, conditional edges, HITL interrupts, `recursion_limit` and retry caps, Postgres checkpointer (resume by `thread_id`)
- LangChain: document loaders and API wrappers

## Core ML
- PyTorch LSTM: six-month audit-failure probability, with Platt or isotonic calibration
- Baselines: logistic regression and XGBoost; the LSTM is promoted only if it wins on AUROC and Brier score
- TensorFlow/Keras intent router: routes requests by cost tier; kept only if it beats a sentence-embedding + logistic-regression baseline on accuracy and measured cost savings

## Generative AI, vision, and privacy
- Gemini API (pinned, currently supported model, behind a provider-agnostic interface): reasoning, explanation drafting, entailment checks, on redacted text only
- LayoutLMv3 for layout-aware field extraction with bounding boxes. It needs OCR input (PaddleOCR or Tesseract), runs locally, and needs fine-tuning on annotated certificates and BOMs. Check the weights' license before any commercial use
- Microsoft Presidio + custom regex recognizers: first-pass PII, price, IBAN, and supplier-ID detection
- Quantized Llama 3 8B (llama.cpp or Ollama): second-pass redaction checker
- Local token vault for reversible pseudonyms. The Deterministic Verifier runs inside the boundary on vault-mapped values
- Leakage test suite: seeds synthetic PII and fails the build if any appears in an outbound payload
- Auth, per-tenant isolation, rate limiting

## Retrieval (RAG)
- ChromaDB with Sentence-Transformers (e.g. all-MiniLM-L6-v2), chunked by legal structure (article, recital, annex)
- BM25 + cross-encoder reranker (hybrid retrieval)
- Metadata: `jurisdiction`, `effective_from`, `superseded_by`, `version_id`, filtered at query time
- Mock issuer registry for the Verifier (real registries needed in production)

## Evaluation, observability, and deployment
- Golden evaluation set of 100-200 labeled cases (forged, expired, scope-mismatched, conflicting-evidence documents)
- Ragas (faithfulness, answer relevance) judged by a different model family from the generator
- Extraction F1 per field, LSTM Brier score and AUROC, citation precision/recall, HITL escalation precision/recall, router accuracy
- GitHub Actions CI gates on regressions
- LangSmith for tracing, latency, and cost
- Vercel for the frontend; Render, Railway, or a self-hosted worker pool for the API. Components that handle raw documents must run inside the trust boundary
