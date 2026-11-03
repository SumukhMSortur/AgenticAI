"""Deterministic, local-only explanation provider for development and tests."""

from backend.app.graph.workflow import ExplanationContext


class FakeLLM:
    """Produce a draft from already-verified fields without network access."""

    def summarize(self, context: ExplanationContext, prompt_version: str) -> str:
        counts = {
            outcome: sum(finding.outcome == outcome for finding in context.findings)
            for outcome in ("pass", "fail", "escalate")
        }
        risk = "unavailable" if context.risk_score is None else f"{context.risk_score:.3f}"
        return (
            f"Deterministic fake explanation ({prompt_version}); "
            f"findings: {counts['pass']} pass, {counts['fail']} fail, "
            f"{counts['escalate']} escalated; six-month risk: {risk}. "
            "The verifier's outcome is authoritative."
        )
