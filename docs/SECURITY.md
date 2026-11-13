# Security

## Security boundary

EcoChain Copilot processes supplier documents that may contain confidential
business data and personal information. Treat uploads, extracted text, model
outputs, and external records as untrusted. Keep raw documents and vault
mappings inside the application trust boundary. The local demo uses a fake
explanation provider; it is not a production deployment profile.

## Controls

- **Authentication and authorization:** passwords are Argon2-hashed; protected
  API routes require signed, expiring JWTs. Roles gate reviewer and tenant
  administrator actions. Resource repositories include the tenant ID in
  lookups; a foreign resource is returned as not found.
- **Uploads:** PDF content type and signature, per-request bytes, batch count,
  page count, encryption state, and parseability are checked before storage.
  Filenames are normalized. Do not expose the upload directory or accept
  arbitrary file types.
- **Prompt injection and decisions:** document/query text is untrusted. The
  deterministic Verifier owns pass/fail/escalate decisions; the explanation
  model receives minimized, locked findings and cannot override the scorecard.
- **PII and egress:** redaction is local. `OutboundGuard` checks payload size,
  image data, vault-known values, tenant consent, and provider field allowlists
  before supported external calls. A rejected payload must not reach a
  provider. Network calls belong in the guarded integration/LLM adapters.
- **Audit integrity:** audit events are append-only at the database layer and
  include a SHA-256 chain. `verify_chain()` detects invalid sequences,
  predecessor hashes, and event contents.
- **Dependency outages:** readiness returns unavailable when PostgreSQL or
  Redis cannot be reached. Rate-limited API work is rejected if Redis is down.
  Workers record visible failures when possible and never turn dependency
  errors into a compliant result.

## Operator requirements

- Replace all development-only credentials and `SECRET_KEY`; keep secrets in
  a secret manager or ignored local environment, never in source control.
- Bind services to private networks, terminate TLS at a trusted proxy, restrict
  database/cache access, and use least-privilege service identities.
- Back up PostgreSQL and uploaded documents; test restore procedures. Protect
  audit data and model artifacts from unauthorized modification.
- Monitor `/readyz`, worker logs/queue depth, failed or stuck jobs, audit-chain
  verification, and disk usage. Investigate `processing` jobs after outages;
  do not manually mark them compliant.
- Review logs for sensitive content before forwarding them. The application
  aims to log identifiers and summaries rather than raw document text.

## Verification

Use the project virtual environment and real PostgreSQL/Redis Compose services:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_privacy_boundary.py backend\tests\leakage -q
.\scripts\test_integration.ps1
.\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_graph_postgres_resume.py -q
```

The integration suite includes cross-tenant resource denial, authentication
and role checks, upload abuse, audit immutability/tampering, and controlled
PostgreSQL/Redis outage-and-recovery tests. The outage test stops services in
the development Compose project and restarts them in cleanup; do not run it
against production or a shared database.

## Residual risks

- Redaction is probabilistic in part and cannot guarantee zero PII leakage.
- Synthetic data, mock issuer records, and curated regulations do not establish
  production accuracy or legal compliance.
- The tested prompt-injection corpus is not exhaustive; document parsing and
  explanations still require human oversight.
- Upload checks do not replace malware scanning, sandboxing, or resource
  isolation for hostile PDFs.
- This checkout has no Git metadata, so its source revision and commit
  provenance cannot be verified here.

Report suspected vulnerabilities through the repository's approved private
security-reporting channel. Do not include production documents or secrets in
reports.
