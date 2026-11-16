# EcoChain Copilot Security Architecture & Threat Model

**Version:** 1.0.0  
**Status:** Production Standard  

---

## 1. Threat Model & Security Boundaries

EcoChain Copilot operates under a **Zero-Trust Enterprise Boundary**. Raw supplier documents, trade pricing, and customer personally identifiable information (PII) must **never** be transmitted to external cloud LLM providers.

```
       [ Customer Network / Ingestion ]
                     │
                     ▼
┌────────────────────────────────────────────────────────┐
│               LOCAL PRIVACY BOUNDARY                   │
│                                                        │
│  1. OCR & Local Document Ingestion (PyMuPDF)           │
│  2. Deterministic PII / Financial Redactor (Presidio)  │
│  3. Envelope-Encrypted Token Vault (AES-256 Fernet)    │
│  4. OutboundGuard Egress Chokepoint                    │
└────────────────────────────────────────────────────────┘
                     │ (Redacted text & rule IDs only)
                     ▼
┌────────────────────────────────────────────────────────┐
│                   CLOUD LLM TIER                       │
│                                                        │
│  * Google Gemini API (Summarization only)              │
│  * Decision-locked: LLM cannot alter verifier verdict  │
└────────────────────────────────────────────────────────┘
```

---

## 2. Cryptographic Controls

### A. Envelope-Encrypted Token Vault
- Sensitive values (Tax IDs, email addresses, personal signatures) are replaced by encrypted pseudonyms.
- Master Key is managed via `VAULT_ENCRYPTION_KEY` and never stored with document checkpoints.

### B. Hash-Chained Audit Trail
- Every pipeline execution event is sequentially hashed:
  `Hash_i = SHA-256(TenantID + Sequence + PrevHash + EventPayload)`
- Database-level trigger `reject_audit_event_mutation()` rejects any `UPDATE` or `DELETE` statements on `audit_events`.
- Regulators can independently verify the hash chain using:
  ```bash
  python -m backend.app.db.audit_cli <org_id>
  ```

---

## 3. Data Classification: What Leaves the Boundary

| Data Type | Leaves Enterprise Boundary? | Destination |
| :--- | :--- | :--- |
| **Raw Supplier PDF** | **NO (0% Egress)** | Local / Private S3 bucket only |
| **Supplier Trade Pricing / Bank Details** | **NO** | Stripped by Presidio / OutboundGuard |
| **PII (Names, Emails, Tax IDs)** | **NO** | Pseudonymized in Token Vault |
| **Redacted Verification Findings** | **YES** | Google Gemini (for natural-language explanation) |
| **Deterministic Rule Outcomes (Pass/Fail)** | **YES** | LLM Explainer input |

---

## 4. Multi-Tenancy & Row-Level Security (RLS)

- Tenancy is enforced at two distinct layers:
  1. **Application Layer:** Repository methods mandate `org_id` / `tenant_id` parameters.
  2. **Database Layer (RLS):** PostgreSQL policies evaluate `current_setting('app.current_org_id', true)`. Cross-org access fails closed at the database driver level.
