# EcoChain Copilot Production Runbook & Incident Response

**Version:** 1.0.0  
**Target:** SRE, Platform Engineers, Compliance Administrators  

---

## 1. Service Health & Readiness Endpoints

The API provides two dedicated observability probes:
* `GET /healthz`: Basic container alive check.
* `GET /readyz`: Comprehensive readiness check confirming:
  - Database connectivity (PostgreSQL query `SELECT 1`)
  - Cache & job queue connectivity (Redis `PING`)
  - Workflow services factory validation

---

## 2. External Registry Outage Procedures

If an authoritative registry (IAF CertSearch, OFAC Sanctions, EUR-Lex) becomes unreachable:
1. **Rule Outcome:** Associated rules fail-safe to `INCONCLUSIVE` (or `status="unavailable"`). **No document is ever marked PASS/Compliant during an external outage.**
2. **Workflow Behavior:** Assessments automatically escalate to `review_required` for human review.
3. **Recovery Action:** Once upstream connectivity is restored, administrators trigger re-evaluation from the dashboard.

---

## 3. Cryptographic Audit Chain Verification & Incident Drill

To audit tamper integrity or prepare a submission for regulatory inquiry:
```bash
# Verify tenant audit trail integrity
docker exec agenticai-main-worker-1 python -m backend.app.db.audit_cli <TENANT_ID>
```
* **Exit Code 0:** All sequential hashes match; zero database records altered or deleted.
* **Exit Code 2:** Hash mismatch detected; inspect payload and database server audit logs immediately.

---

## 4. Disaster Recovery & Database Restoration

```bash
# Backup production PostgreSQL database
docker exec -t agenticai-main-postgres-1 pg_dump -U ecochain ecochain > backup_$(date +%Y%m%d).sql

# Restore procedure on clean host
cat backup_20261116.sql | docker exec -i agenticai-main-postgres-1 psql -U ecochain -d ecochain
```

---

## 5. Secret & Encryption Key Rotation

* **Token Vault Key (`VAULT_ENCRYPTION_KEY`):**
  When rotating the Fernet envelope master key, use `backend/app/privacy/vault.py` re-encryption utility to migrate existing pseudonyms before updating the environment variable.
* **Supabase JWT Secret:**
  Update `SUPABASE_JWT_SECRET` in `.env`. The backend validates incoming tokens against the new signing key on the next request.
