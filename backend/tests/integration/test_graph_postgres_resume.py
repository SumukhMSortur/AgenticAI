"""PostgreSQL-backed interrupt/resume verification for durable HITL checkpoints."""

import os

import pytest
from langgraph.checkpoint.postgres import PostgresSaver

from backend.app.core.config import settings
from backend.app.graph.workflow import (
    ExplanationContext,
    ReviewDecision,
    WorkflowServices,
    build_workflow,
    invoke_workflow,
    postgres_checkpointer,
    resume_workflow,
)
from backend.app.router.intent import RouteDecision
from backend.app.verifier.engine import Verifier
from scripts.evaluate_verifier import DEFAULT_DATASET, _case_inputs


class StaticRouter:
    def route(self, _query: str) -> RouteDecision:
        return RouteDecision("certificate_assessment", 1.0, {"certificate_assessment": 1.0})


class NoopStage:
    def __call__(self, _state: dict) -> dict[str, object]:
        return {}


class FakeExplainer:
    def summarize(
        self, _context: ExplanationContext, _prompt_version: str
    ) -> str:
        return "Durable review completed."


class FakeAuditRecorder:
    def record(self, _event: dict[str, object]) -> str:
        return "postgres-resume-audit"


def _services() -> WorkflowServices:
    return WorkflowServices(
        router=StaticRouter(),
        redact=NoopStage(),
        extract=NoopStage(),
        enrich=NoopStage(),
        forecast=NoopStage(),
        retrieve=NoopStage(),
        verifier=Verifier(),
        explainer=FakeExplainer(),
        audit_recorder=FakeAuditRecorder(),
    )


@pytest.mark.integration
def test_postgres_checkpoint_survives_saver_restart_and_resumes_hitl() -> None:
    connection_string = (
        os.environ.get("ECOCHAIN_TEST_POSTGRES_URL") or settings.TEST_DATABASE_URL
    )
    if not connection_string:
        pytest.skip("Set TEST_DATABASE_URL or ECOCHAIN_TEST_POSTGRES_URL for PostgreSQL coverage.")

    import json

    cases = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))["cases"]
    case = next(row for row in cases if row["expected_escalation"])
    claim, context = _case_inputs(case)
    state = {
        "job_id": case["case_id"],
        "tenant_id": "TENANT-POSTGRES-TEST",
        "thread_id": f"postgres-{case['case_id']}",
        "assessment_date": context.assessment_date,
        "query": case["description"],
        "claims": [claim],
        "verification_context": context,
        "step_counts": {},
    }
    with postgres_checkpointer(connection_string) as checkpointer:
        assert isinstance(checkpointer, PostgresSaver)
        graph = build_workflow(_services(), checkpointer=checkpointer)
        paused = invoke_workflow(graph, state)
        assert paused.get("__interrupt__")

    with postgres_checkpointer(connection_string) as restarted_checkpointer:
        restarted_graph = build_workflow(_services(), checkpointer=restarted_checkpointer)
        completed = resume_workflow(
            restarted_graph,
            thread_id=state["thread_id"],
            decision=ReviewDecision(
                reviewer_id="integration-reviewer",
                decision="approved",
                notes="Resume after saver restart.",
            ),
        )
    assert completed["scorecard"].overall_status == case["expected_overall_status"]
    assert completed["audit_event_id"] == "postgres-resume-audit"
