# EcoChain Copilot: Model Cards & Licensing Register

## 1. Document Extraction Models

### LayoutLMv3 / LayoutLMv3-base
- **Architecture:** Multi-modal transformer for document AI (text, layout, image).
- **Intended Use:** Structured token classification and spatial bounding box extraction for compliance documents (certificates, BOMs, invoices, test reports).
- **Licensing Constraint (CRITICAL):**
  - Microsoft LayoutLMv3 pretrained model weights are released under a non-commercial CC BY-NC-SA 4.0 license.
  - **Architectural Safeguard:** The extractor is strictly encapsulated behind the abstract `Extractor` interface (`backend/app/extraction/base.py`). In commercial environments where CC BY-NC-SA 4.0 is prohibited, the system uses the production-ready `HeuristicExtractor` or permissible open-weights models (e.g., Donut, LayoutLMv2 under permissive terms, or pure OCR + geometric layout parser) with zero disruption to the downstream pipeline.
- **Evaluation:** Evaluated on held-out synthetic supplier certificates in `reports/extraction.json`.

---

## 2. Predictive Risk Forecasting Models

### PyTorch LSTM (Audit Failure Forecaster)
- **Architecture:** 2-layer Recurrent Neural Network (LSTM) with hidden dimension 64, dropout 0.2, and Platt/isotonic probability calibration.
- **Input:** 36-month normalized sequence of environmental, labor, and corrective audit signals.
- **Output:** Calibrated 6-month probability of audit failure ($p\_fail\_6m \in [0.0, 1.0]$).
- **Promotion Rule:** The LSTM is deployed if and only if it outperforms both baseline models (Logistic Regression and XGBoost) on AUROC and Brier score.
- **Evaluation:** Reported in `reports/risk.json`.

---

## 3. Privacy & Redaction Models

### Presidio Analyzer + SpaCy `en_core_web_md`
- **License:** MIT License.
- **Role:** First-pass deterministic and NER detection of names, addresses, emails, phones, IBANs, and custom regex financial identifiers.
- **Execution:** 100% local inside the enterprise trust boundary.

### Quantized Llama 3 8B (Ollama / GGUF)
- **License:** Meta Llama 3 Community License.
- **Role:** Second-pass redaction checker flagging residual sensitive spans.
- **Safety Fallback:** Fail-closed. If Ollama is enabled and encounters an error or timeout, the system escalates the run to human review rather than risking data leakage.

---

## 4. Generative AI & Explanation Models

### Gemini API (Configurable via `GEMINI_MODEL`)
- **Role:** Drafts explanations and human-readable compliance summaries from locked Verifier verdicts.
- **Choke Point:** Invocations pass exclusively through `outbound_guard.py`. Raw text and images are strictly blocked; only redacted, pseudonymized text reaches the API.
