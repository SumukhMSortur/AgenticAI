"""V-PAGE-001: escalate on missing, inconsistent, or gapped page numbering."""

import re
from collections.abc import Sequence

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict

_PAGE_PATTERN = re.compile(r"\bpage\s+(\d+)\s+of\s+(\d+)\b", re.IGNORECASE)


def check(
    page_claims: Sequence[str] | None,
    actual_page_count: int | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Validate page labels against each other and the observed document page count."""
    if page_claims is None:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-PAGE-001",
            outcome="escalate",
            reason_code="PAGE_COUNT_EVIDENCE_MISSING",
            details={"rationale": "Page count evidence is missing.", "priority": "normal"},
            evidence_ids=evidence_ids,
        )
    if not page_claims:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-PAGE-001",
            outcome="pass",
            reason_code="PAGE_NUMBERING_NOT_PRESENT",
            details={"rationale": "No explicit page numbering claims were found."},
            evidence_ids=evidence_ids,
        )
    parsed: list[tuple[int, int]] = []
    malformed: list[str] = []
    for text in page_claims:
        match = _PAGE_PATTERN.search(text)
        if match is None:
            malformed.append(text)
        else:
            parsed.append((int(match.group(1)), int(match.group(2))))
    if malformed or not parsed or actual_page_count is None or actual_page_count < 1:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-PAGE-001",
            outcome="escalate",
            reason_code="PAGE_NUMBERING_UNREADABLE",
            details={
                "rationale": "Page numbering or actual page count could not be verified.",
                "unreadable_claims": malformed,
                "actual_page_count": actual_page_count,
                "priority": "normal",
            },
            evidence_ids=evidence_ids,
        )
    pages = [page for page, _ in parsed]
    totals = {total for _, total in parsed}
    expected_total = next(iter(totals)) if len(totals) == 1 else None
    has_gap = (
        len(set(pages)) != len(pages)
        or sorted(set(pages)) != list(range(1, max(pages) + 1))
    )
    if (
        expected_total is None
        or expected_total != actual_page_count
        or has_gap
        or any(page < 1 or page > total for page, total in parsed)
    ):
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-PAGE-001",
            outcome="escalate",
            reason_code="PAGE_COUNT_MISMATCH",
            details={
                "rationale": "Claimed page numbering has gaps or conflicts with the document.",
                "claimed_pages": sorted(set(pages)),
                "claimed_totals": sorted(totals),
                "actual_page_count": actual_page_count,
                "priority": "normal",
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-PAGE-001",
        outcome="pass",
        reason_code="PAGE_COUNT_MATCH",
        details={
            "rationale": "Claimed pages are contiguous and match the actual page count.",
            "page_count": actual_page_count,
        },
        evidence_ids=evidence_ids,
    )
