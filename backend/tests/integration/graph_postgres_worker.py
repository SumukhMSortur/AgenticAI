"""Child process used to prove PostgreSQL checkpoint durability across restarts."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.domain.models import EvidenceItem, GraphState
from backend.app.graph.workflow import (
    ExplanationContext,
    ReviewDecision,
    SqlAlchemyAuditRecorder,
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
        return RouteDecision(
            "certificate_assessment",
            1.0,
            {"certificate_assessment": 1.0},
        )


class NoopStage:
    def __call__(self, _state: GraphState) -> dict[str, object]:
        return {}


class FakeExplainer:
    def summarize(self, _context: ExplanationContext, _prompt_version: str) -> str:
        return "Durable review completed."


def load_golden_cases() -> list[dict[str, Any]]:
    payload = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    return payload["cases"]


def _services(
    connection_string: str,
    *,
    recorder_factory: sessionmaker[Session] | None = None,
) -> WorkflowServices:
    factory = recorder_factory
    if factory is None:
        engine = create_engine(connection_string, pool_pre_ping=True)
        factory = sessionmaker(bind=engine)
    return WorkflowServices(
        router=StaticRouter(),
        redact=NoopStage(),
        extract=NoopStage(),
        enrich=NoopStage(),
        forecast=NoopStage(),
        retrieve=NoopStage(),
        verifier=Verifier(),
        explainer=FakeExplainer(),
        audit_recorder=SqlAlchemyAuditRecorder(factory),
    )


def _initial_state(
    case: dict[str, Any],
    *,
    thread_id: str,
    tenant_id: str,
) -> GraphState:
    claim, context = _case_inputs(case)
    evidence = EvidenceItem(
        evidence_id=claim.evidence_ids[0],
        kind="extracted_field",
        ref={"doc_id": claim.doc_id, "page": claim.page},
    )
    return {
        "job_id": case["case_id"],
        "tenant_id": tenant_id,
        "thread_id": thread_id,
        "assessment_date": context.assessment_date,
        "query": case["description"],
        "claims": [claim],
        "evidence": [evidence],
        "verification_context": context,
        "step_counts": {},
        "prompt_version": "postgres-process-restart-v1",
    }


def run_worker(
    mode: str,
    connection_string: str,
    thread_id: str,
    tenant_id: str,
    case_id: str,
) -> None:
    case = next(row for row in load_golden_cases() if row["case_id"] == case_id)
    services = _services(connection_string)
    with postgres_checkpointer(connection_string) as checkpointer:
        graph = build_workflow(services, checkpointer=checkpointer)
        if mode == "pause":
            result = invoke_workflow(
                graph,
                _initial_state(
                    case,
                    thread_id=thread_id,
                    tenant_id=tenant_id,
                ),
            )
            if not result.get("__interrupt__"):
                raise RuntimeError("expected the graph to pause for human review")
            print(
                "PAUSED:"
                + json.dumps(
                    {"thread_id": thread_id, "interrupt": True},
                    sort_keys=True,
                ),
                flush=True,
            )
            sys.stdin.readline()
            return

        if mode != "resume":
            raise ValueError(f"unsupported child worker mode: {mode}")
        result = resume_workflow(
            graph,
            thread_id=thread_id,
            decision=ReviewDecision(
                reviewer_id="process-restart-reviewer",
                decision="approved",
                notes="Resume after process and PostgreSQL container restart.",
            ),
        )
        scorecard = result.get("scorecard")
        if scorecard is None:
            raise RuntimeError("resumed workflow did not produce a scorecard")
        print(
            "RESUMED:"
            + json.dumps(
                {
                    "thread_id": thread_id,
                    "overall_status": scorecard.overall_status,
                    "audit_event_id": result["audit_event_id"],
                    "verdicts": {
                        verdict.rule_id: verdict.outcome for verdict in result["verdicts"]
                    },
                },
                sort_keys=True,
            ),
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pause", "resume"))
    parser.add_argument("connection_string")
    parser.add_argument("thread_id")
    parser.add_argument("tenant_id")
    parser.add_argument("case_id")
    arguments = parser.parse_args()
    run_worker(
        arguments.mode,
        arguments.connection_string,
        arguments.thread_id,
        arguments.tenant_id,
        arguments.case_id,
    )


if __name__ == "__main__":
    main()
