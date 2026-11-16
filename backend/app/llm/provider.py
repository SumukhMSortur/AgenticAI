"""Production-grade LLM provider interface and implementations."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from backend.app.core.config import settings
from backend.app.graph.workflow import ExplanationContext
from backend.app.privacy.outbound_guard import OutboundGuard

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract interface for LLM explanation generation."""

    @abstractmethod
    def summarize(self, context: ExplanationContext, prompt_version: str) -> str:
        """Generate human-readable audit explanation from verified findings."""
        pass


class GeminiLLMProvider(LLMProvider):
    """Production provider using Google Gemini GenAI SDK via OutboundGuard chokepoint."""

    def __init__(self, guard: OutboundGuard | None = None) -> None:
        self.guard = guard or OutboundGuard()
        self.model = settings.GEMINI_MODEL
        self.api_key = settings.GEMINI_API_KEY

    def summarize(self, context: ExplanationContext, prompt_version: str) -> str:
        # 1. Structure the prompt strictly from redacted findings and rule verdicts
        counts = {
            outcome: sum(finding.outcome == outcome for finding in context.findings)
            for outcome in ("pass", "fail", "escalate")
        }
        risk_str = "unavailable" if context.risk_score is None else f"{context.risk_score:.3f}"
        
        prompt_payload = (
            f"Role: Compliance Auditor Explainer\n"
            f"Prompt Version: {prompt_version}\n"
            f"Findings: {counts['pass']} PASS, {counts['fail']} FAIL, {counts['escalate']} ESCALATED\n"
            f"6-Month Audit Risk: {risk_str}\n"
            f"Rule Details:\n"
        )
        for f in context.findings:
            prompt_payload += f"- Rule {f.rule_id}: {f.outcome} ({f.reason_code})\n"

        # 2. Strict Outbound PII / Leakage Guard check before dispatching
        # Raises PrivacyViolationError if any raw PII or unredacted token leaks
        self.guard.verify_and_log_payload(
            payload=prompt_payload,
            tenant_id="cloud-egress",
        )

        # 3. Call Gemini if API key configured, otherwise use templated explanation
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured; providing structured deterministic explanation.")
            return (
                f"Compliance Assessment Summary ({prompt_version}): "
                f"Evaluated {len(context.findings)} rules resulting in {counts['pass']} compliant, "
                f"{counts['fail']} non-compliant, and {counts['escalate']} requiring human review. "
                f"Projected 6-month factory audit failure risk is {risk_str}. "
                "All compliance verdicts are strictly determined by deterministic rules."
            )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt_payload,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=500,
                ),
            )
            explanation = response.text or ""
            return f"{explanation.strip()}\n\n[Note: Explanations are AI-generated; verdicts are determined solely by deterministic rules.]"
        except Exception as exc:
            logger.error("Gemini API call failed: %s; falling back to deterministic explanation.", exc)
            return (
                f"Compliance Summary ({prompt_version}): "
                f"{counts['pass']} rules passed, {counts['fail']} failed, {counts['escalate']} escalated. "
                f"Factory risk score: {risk_str}."
            )


class FakeLLMProvider(LLMProvider):
    """Deterministic local provider for testing."""

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
