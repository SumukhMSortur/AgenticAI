# Live Provider Verification

**Checked:** 2026-11-11  
**Result:** Phase 14 providers remain disabled. This check did not establish the
complete endpoint, authentication, terms, and freshness details required to
safely enable any live integration.

| Provider | Official source checked | Observed result | Remaining verification |
|---|---|---|---|
| Open Supply Hub | [API documentation](https://opensupplyhub.org/api/docs/) | Documentation page is reachable. A prior unauthenticated request to the production-locations resource returned HTTP 401. | Confirm the current API schema and base/resource URLs, authentication and required scopes, rate limits, license/attribution, and permitted snapshot redistribution. Do not treat the HTTP 401 as proof of the required authentication method. |
| EU sanctions | [EEAS sanctions page](https://www.eeas.europa.eu/eeas/consolidated-list-sanctions_en) | The checked URL returned HTTP 404. | Identify an authoritative current EU consolidated-list source and confirm its download/API, format, licensing/reuse terms, update cadence, and data provenance. |
| OFAC sanctions | [Sanctions List Service](https://ofac.treasury.gov/sanctions-list-service) | The official page describes SDN and consolidated non-SDN lists and offers downloadable data. | Confirm exact current file URLs and formats, update cadence, integrity checks, and applicable reuse/redistribution terms before building an importer. |
| EUR-Lex | [Data reuse webservice help](https://eur-lex.europa.eu/content/help/data-reuse/webservice.html) | The official URL returned no usable documentation in this check. | Confirm an official feed/API for the target CSDDD/ESPR acts, query contract, terms, version and supersession metadata, and update cadence. |

No live provider adapter, scheduler, or outbound request is enabled. Existing
local snapshots and the human approval queue remain the only supported source
for external evidence. Missing, stale, or unavailable data must escalate and
must never produce an automatic pass. Exact sanctions identifiers must fail
with critical human review; fuzzy/name-only matches must escalate. Regulation
updates must remain proposals until an authorized reviewer approves them.

Before enabling a provider, record source URLs and verification date, obtain
written confirmation of usage terms where needed, implement requests only
through `OutboundGuard`, use an allowlisted minimal payload, add recorded
fixtures and outage tests, and verify provenance/freshness and audit events
end-to-end. Routine tests must not make live or paid calls.
