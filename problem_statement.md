# EcoChain Copilot: Problem Statement

## The problem

Large apparel brands source from hundreds of factories worldwide. Each supplier produces a steady stream of messy evidence: scanned certificates, Bills of Materials (BOMs), chemical test reports, invoices, and multi-year audit histories. Compliance officers read these by hand to verify claims such as "100% organic cotton" or "no restricted substances." This is slow, inconsistent between reviewers, done after purchase orders are placed, and it treats audit history as a record rather than a signal for predicting future failures.

## The regulatory context

The EU Corporate Sustainability Due Diligence Directive (CSDDD) requires in-scope companies to identify, prevent, and remediate adverse environmental and human-rights impacts in their value chains. It was substantially narrowed by the Omnibus I Directive (EU) 2026/470, in force since 18 March 2026:

- It applies only to companies with more than 5,000 employees and more than EUR 1.5 billion in net worldwide turnover.
- There is a single application date of 26 July 2029 (national transposition by 26 July 2028).
- The climate transition plan obligation and the EU-wide civil liability regime were removed, and value-chain mapping became a risk-based exercise.

Other regimes also drive demand for supplier evidence (EU Digital Product Passport / ESPR, anti-greenwashing rules, the Forced Labour Regulation). Verify their scope and dates before citing them in any deliverable.

## Why naive LLM automation is not the answer

1. **Hallucinated compliance:** a confident wrong answer creates a false record of due diligence.
2. **Data leakage:** supplier documents contain pricing, contract terms, bank details, and personal data that must not leave the enterprise boundary.
3. **No audit trail:** without recorded model, prompt, document, and law version, a decision cannot be defended.

## What EcoChain Copilot does

A multi-agent system in which language models explain and deterministic code decides. It reads supplier documents locally, redacts sensitive data, extracts structured fields with page and bounding-box provenance, retrieves the version-correct regulation text, verifies claims with rule-based checks, forecasts each factory's six-month audit-failure risk, and escalates uncertain or failing cases to a human reviewer.

## How the technologies map to jobs

| Job | Technology |
|---|---|
| Orchestration, human-in-the-loop pauses | LangGraph (Postgres checkpointer) + LangChain |
| Cheap query routing | Lightweight TensorFlow/Keras DNN, kept only if it beats an embedding + logistic-regression baseline |
| Risk forecast | PyTorch LSTM, calibrated, benchmarked against logistic regression and XGBoost |
| Fact-checking | RAG over versioned regulations (ChromaDB, hybrid BM25 + dense retrieval, reranker, citation entailment check) |
| Document reading | Local OCR + LayoutLMv3 for layout-aware extraction with bounding boxes |
| Privacy | Presidio + regex, then quantized Llama 3 as a second-pass checker, with reversible pseudonyms |
| Decisions | Deterministic Verifier (expiry, issuer registry, scope-to-BOM match, cross-document consistency) |
| Dashboard | Next.js + TypeScript, FastAPI backend, SSE streaming: risk gauge, audit checklist, and citations with source-page highlighting |

See `ecochain_copilot_architecture.md` for the full design and known limitations.
