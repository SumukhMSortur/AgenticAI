# EcoChain Copilot: Dataset Approach

No single public dataset covers messy supplier PDFs together with audit time series, so combine open sources with synthetic data. Verify each source's contents and license before relying on it (figures below come from earlier notes and were not independently confirmed).

## 1. Real supplier and factory data
**Open Supply Hub (OS Hub):** open database and API of apparel production locations and supplier networks. Use it for realistic factory names, locations, and parent-company links instead of invented companies.

## 2. Real ESG and compliance text
**SustainableQA (University of Innsbruck, GitHub):** large Q&A set built from corporate sustainability reports (EU Taxonomy, ESG). Use it to evaluate the Compliance RAG Agent and greenwashing detection. Confirm its size and license in the repository.

## 3. Regulation structures
**OpenEPCIS DPP-ready (GitHub):** JSON schemas and vocabulary for the EU Digital Product Passport and textiles. Use them to shape the structured output. Confirm the vocabulary scope in the repository.

## 4. Regulation corpus for ChromaDB
Curate the actual legal texts (CSDDD as amended by Omnibus I, plus other regimes you decide to cover) from EUR-Lex. Chunk by article, recital, and annex, and add `jurisdiction`, `effective_from`, `superseded_by`, and `version_id` metadata. This corpus must be curated and versioned manually or via a controlled ingestion pipeline.

## 5. Synthetic data (you must create it)

### Audit history for the LSTM
- Generate several hundred factories (not 50) with 24-36 months of numeric audit signals each (e.g. carbon output, labor violations, certificate lapses).
- Define the label explicitly: "fails an audit within the next 6 months." The model predicts a probability, not a month-25 score.
- Embed realistic patterns (trends, seasonality, noise, drift before failure) and keep a held-out set split by factory.
- State clearly in the evaluation report that, because the data is synthetic, metrics measure generator fidelity, not real-world audit risk.

### Visual documents for OCR and LayoutLMv3
- 10-20 hand-made PDFs are enough for demos but not for fine-tuning or evaluation. Generate hundreds programmatically (templated HTML to PDF with scan noise, skew, stamps, signatures) for GOTS-style certificates, BOMs, invoices, and chemical test reports.
- Annotate fields (type, issuer, validity dates, scope, BOM lines) to train and score extraction F1.

### Golden evaluation set
Build 100-200 labeled cases that include forged, expired, scope-mismatched, and conflicting-evidence documents. Use them for CI regression gates.

### Privacy test data
Seed synthetic PII (names, IBANs, emails, prices, supplier IDs) into documents for the leakage test suite.
