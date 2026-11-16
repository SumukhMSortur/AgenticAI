# Forgery Red-Team Evaluation Report (Phase 4B)

**Date:** 2026-11-16  
**Module:** `backend/app/verifier/authenticity.py`  
**Test Suite:** `backend/tests/unit/test_forgery_authenticity.py`

---

## 1. Attack Vectors Evaluated

| Attack Type | Technique Used by Forger | System Detection Mechanism | Result |
| :--- | :--- | :--- | :--- |
| **Plausible Forgery** | Correct format, valid future date, genuine issuer name, but fabricated number. | Flagged as `CONSISTENT_NOT_VERIFIED` because certificate number does not exist in the external registry. | **Blocked from Auto-Approval** (100% routed to reviewer) |
| **Broken Digital Signature** | PDF modified after cryptographic signing (tampered dates or scope). | `FOR-SIG-001`: Signature verification failure / modified after signing. | **Caught (SUSPECTED_TAMPERING)** |
| **Font & Compression Tamper** | Dates or company name overlaid onto a scanned certificate. | `FOR-MET-001`: Font mismatch and inconsistent compression analysis. | **Caught (SUSPECTED_TAMPERING)** |
| **Independent Verification** | Genuine certificate verified against scheme database with valid digital signature. | Full match in external scheme registry. | **Approved (`INDEPENDENTLY_VERIFIED`)** |

---

## 2. Authenticity Levels Distribution

- `INDEPENDENTLY_VERIFIED`: Auto-approval permitted if all 18 verifier rules pass.
- `CONSISTENT_NOT_VERIFIED`: Never auto-approved. Automatically routes to human auditor or generates an out-of-band issuer confirmation request.
- `SUSPECTED_TAMPERING`: Immediate failure and escalation.
- `UNVERIFIABLE`: Clear warning banner surfaced in UI scorecard.
