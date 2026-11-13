# ECOCHAIN COPILOT: ADDENDUM A (LIVE EXTERNAL DATA)

> Amends `ECOCHAIN_MASTER_PROMPT.md`. Where this file and the master prompt conflict, **this file wins** for the topics it covers. Record it in `docs/DECISIONS.md` as "ADR: live external data".
>
> **How to apply mid-build:** send your agent: *"Read ECOCHAIN_ADDENDUM_LIVE_DATA.md. Finish the Phase 5 gate first without changing its scope, then apply Retrofits R1-R4 as a separate commit (`chore: addendum-A retrofits`), and follow the amended Phases 6 and 9 and the new Phase 14."*

---

## A1. Principles (non-negotiable)

1. **Snapshot-first.** Prefer downloading a licensed snapshot and matching it **locally** over live per-document queries. A live lookup of a factory name reveals the client's business relationship; a local match does not.
2. **Live calls are opt-in per tenant** and pass through the outbound guard with a per-provider **field allowlist**. Never send document text, vault values, pseudonym maps, or images.
3. **Verifier stays pure.** It never touches the network. External data is fetched by an `enrich` node and the Verifier receives it as input evidence.
4. **Provenance on everything:** every external record carries `source`, `fetched_at`, `snapshot_hash`, `license`/`terms_url`, and is written to the audit log. The scorecard shows "per <source>, as of <date>".
5. **Fail closed.** Provider down, stale data, or unparsable response yields `escalate`, never `pass`.
6. **Absence is not proof.** "Not found" escalates; it never auto-fails.
7. **Respect terms.** Use official APIs or documented bulk downloads only. **No scraping** of sites whose terms don't allow it. Verify each source's current endpoint, format, rate limits, and license from its **official documentation at build time**, record them in `docs/DECISIONS.md`, and never hardcode them from memory.
8. **No LSTM contamination.** External signals (news, sanctions, registry hits) are rule-based escalation inputs and display context. They are **not** features of the LSTM: there is no labeled history to train on.
9. **No new dependencies without the lock process.** Use `httpx` and the stdlib (`xml.etree`, `difflib`) where possible; scheduling uses Celery beat.

## A2. Retrofits to completed phases (do once, in one commit, with tests)

- **R1 (Phase 1, DB):** add migrations for `external_sources` (id, name, terms_url, license, max_age_days), `external_snapshots` (source_id, fetched_at, content_hash, record_count, path), `external_records` (snapshot_id, key, normalized_name, country, payload JSONB), `watchlist_hits` (job_id, source_id, record_key, match_type, score), `regulation_update_proposals` (source, detected_at, candidate_version_id, status, reviewer_id). Add audit event types `external_lookup`, `external_refresh`, `regulation_update_proposed`, `regulation_update_decided`.
- **R2 (Phase 3, privacy):** extend `outbound_guard.py` from "only door to cloud LLMs" to **"only door to any external network"**. Add `ExternalCallPolicy` (tenant opt-in flag, per-provider allowlisted fields, max payload size). Extend the leakage suite: seeded PII and vault values must not appear in any external-call payload; add a codebase test that fails if `httpx`/`requests` is used outside `integrations/` and `llm/` via the guard.
- **R3 (Phase 5, RAG):** make regulation ingestion **idempotent and version-aware** (`ingest(source_id, version_id)`); add `propose_update()` that creates a pending proposal. The corpus is **never changed autonomously**; a human approves in the review queue, and approval records the decision in the audit log.
- **R4 (Phase 1, contracts):** extend `EvidenceItem.kind` with `"external_record"`, `"watchlist_hit"`, `"regulation_update"`, and add `ExternalRef {source, fetched_at, snapshot_hash, record_key}` to `EvidenceItem.ref` validation.

## A3. Amended Phase 6 (Verifier): new rules

All pure functions on snapshot data passed in as evidence; each with boundary tests.

| Rule | Check | Outcome |
|---|---|---|
| V-EXT-001 | Facility not found in the local production-location snapshot (name + country, fuzzy ratio < 0.75) | escalate |
| V-EXT-002 | Found, but country mismatch, or name ratio 0.75-0.90 | escalate |
| V-EXT-003 | Found, but parent company differs from the document | escalate |
| V-EXT-900 | Snapshot older than `max_age_days`, or source unavailable | escalate |
| V-SANC-001 | Exact identifier match (registration number, address+name) against a watchlist | **fail + critical mandatory human review** |
| V-SANC-002 | Name-only or fuzzy (>= 0.90) match | escalate (critical priority) |

Add a `priority` field to escalations (`normal` / `critical`); critical items sort first in the review queue.

## A4. Amended Phase 9 (graph)

Flow becomes: `route -> redact -> extract -> **enrich** -> forecast -> retrieve -> verify -> decide -> (hitl_wait) -> explain_publish -> record`.

- `enrich` runs **inside the boundary** on vault-mapped values, performing **local** matching against stored snapshots. It calls a live provider only if the tenant opted in, through the guard. It emits `EvidenceItem`s of the new kinds and `watchlist_hits`.
- Add `enrich` to the append-only reducers, retry caps, and SSE events. Provider failure routes to the escalation edge, never to pass.

## A5. New Phase 14: Live integrations

Build in `backend/app/integrations/` with a `Provider` interface (`refresh()`, `lookup()`, `health()`), plus fakes.

1. **Open Supply Hub provider**
   - Snapshot mode (default): download within the account's allowed limits and terms, normalize into `external_records`, build a local fuzzy index (name, country, address, parent company).
   - Live mode (opt-in): authenticated API calls (token from env), allowlisted fields only (facility name, country), respecting rate limits and pagination. Check the current endpoint (the older `/facilities` vs. newer `v1/production-locations`) in the official docs and record the choice.
2. **Sanctions/watchlist provider(s)**
   - Ingest official EU and OFAC list downloads (verify current URLs, formats, update cadence, and terms). Normalize names (case, diacritics, transliteration variants, aliases) and identifiers. Local matching only; no outbound supplier names.
3. **Regulation watcher**
   - Scheduled check of official EUR-Lex feeds for relevant acts; on a detected change, create a `regulation_update_proposals` row and notify reviewers. Approval triggers `ingest()` (R3) with `effective_from` / `superseded_by` handled. No auto-publish.
4. **Adverse media: out of scope by default.** Implement only the interface and a disabled feature flag; document why (false positives, entity-resolution risk, privacy).

Operations: Celery beat schedules (`make refresh-external` for manual runs), ETag/`If-Modified-Since`, retries with backoff, circuit breaker, per-source TTL from `external_sources.max_age_days`, cache in Postgres (and Redis for hot lookups).

Testing: recorded JSON fixtures for every provider (no live network in CI), determinism tests, stale-snapshot and provider-down tests (must escalate), terms/license recorded for each source, extended leakage suite (R2), and a test that a sanctions exact match yields `fail` + `critical`.

API/UI additions: `GET /v1/integrations/status` (source, last refresh, age, record count, health), tenant setting to enable live lookups, admin view for pending regulation proposals (approve/reject), scorecard rows showing external evidence with "source, as of date" and a **staleness badge**.

## A6. Additions to the final acceptance checklist

15. No outbound call to any external service except through the guard; seeded PII never appears in external payloads.
16. Every external fact on a scorecard shows source and as-of date and is reproducible from the audit log and snapshot hash.
17. Sanctions exact match yields `fail` + critical review; fuzzy match escalates; provider outage escalates.
18. Regulation updates never reach the corpus without a recorded human approval.
19. All source endpoints, formats, and terms are documented in `docs/DECISIONS.md` from official documentation, with the date checked.
20. Known Limitations updated: snapshot freshness, matching false positives/negatives, mocked vs. real registries, and that external signals do not feed the LSTM.
