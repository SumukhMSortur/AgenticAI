"""LangGraph workflow with bounded retries, deterministic decisions, and HITL pause/resume."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import yaml
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START
from langgraph.graph._node import StateNode
from langgraph.graph.state import StateGraph
from langgraph.types import Command, RetryPolicy, interrupt
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.audit_log import append_audit_event
from backend.app.domain.models import (
    EscalationState,
    GraphState,
    Scorecard,
    ScorecardLine,
)
from backend.app.router.intent import RouteDecision
from backend.app.verifier.engine import Verifier

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "graph.yaml"

_INTENT_ROUTES: dict[str, Literal["retrieval_only", "full_analysis", "out_of_scope"]] = {
    "certificate_assessment": "full_analysis",
    "facility_lookup": "full_analysis",
    "risk_forecast": "full_analysis",
    "review_status": "full_analysis",
    "regulation_retrieval": "retrieval_only",
    "general_help": "retrieval_only",
    "out_of_scope": "out_of_scope",
}
_CHECKPOINT_MODELS = (
    "BBox",
    "ExtractedField",
    "ExternalRef",
    "ExternalSnapshotRecord",
    "ExternalSnapshot",
    "ExternalLookup",
    "SanctionsMatch",
    "VerificationContext",
    "EvidenceItem",
    "Claim",
    "Verdict",
    "RiskForecast",
    "DocumentRef",
    "RedactedPage",
    "EscalationState",
    "ScorecardLine",
    "Scorecard",
)


class GraphSettings(BaseModel):
    """Explicit limits and risk cutoffs for workflow execution."""

    max_node_attempts: int = Field(ge=1, le=5)
    recursion_limit: int = Field(ge=10, le=100)
    risk_reaudit_threshold: float = Field(ge=0.0, le=1.0)
    risk_review_threshold: float = Field(ge=0.0, le=1.0)
    risk_critical_threshold: float = Field(ge=0.0, le=1.0)
    prompt_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_risk_thresholds(self) -> GraphSettings:
        if not (
            self.risk_reaudit_threshold
            <= self.risk_review_threshold
            <= self.risk_critical_threshold
        ):
            raise ValueError("graph risk thresholds must be nondecreasing")
        return self


class RetryableWorkflowError(RuntimeError):
    """Explicitly marked transient pipeline failure eligible for bounded retry."""


def load_graph_settings(path: Path = _CONFIG_PATH) -> GraphSettings:
    """Load bounded workflow settings from the checked-in graph configuration."""
    with path.open(encoding="utf-8") as config_file:
        settings: Any = yaml.safe_load(config_file)
    if not isinstance(settings, dict):
        raise ValueError(f"Graph configuration must be a mapping: {path}")
    return GraphSettings.model_validate(settings)


class Router(Protocol):
    """Intent classification interface used by the first graph node."""

    def route(self, query: str) -> RouteDecision: ...


class PipelineStage(Protocol):
    """Injected implementation for one isolated processing stage."""

    def __call__(self, state: GraphState) -> GraphState: ...


class Explainer(Protocol):
    """Draft-only LLM interface; it cannot return domain decisions."""

    def summarize(
        self,
        context: ExplanationContext,
        prompt_version: str,
    ) -> str: ...


class AuditRecorder(Protocol):
    """Persistence boundary for final workflow audit events."""

    def record(self, event: dict[str, object]) -> str: ...


@dataclass(frozen=True)
class VerifiedFinding:
    """Minimal LLM-facing finding with no document text or verifier details."""

    claim_id: str
    rule_id: str
    outcome: Literal["pass", "fail", "escalate"]
    reason_code: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExplanationContext:
    """Privacy-minimized, decision-locked context for explanation drafting."""

    overall_status: Literal[
        "compliant", "non_compliant", "review_required", "informational"
    ]
    findings: tuple[VerifiedFinding, ...]
    evidence_ids: tuple[str, ...]
    risk_score: float | None


@dataclass(frozen=True)
class WorkflowServices:
    """Required external implementations; no silent stage fallbacks are provided."""

    router: Router
    redact: PipelineStage
    extract: PipelineStage
    enrich: PipelineStage
    forecast: PipelineStage
    retrieve: PipelineStage
    verifier: Verifier
    explainer: Explainer
    audit_recorder: AuditRecorder


class ReviewDecision(BaseModel):
    """Validated reviewer response used to resume an interrupted graph."""

    reviewer_id: str = Field(min_length=1)
    decision: Literal["approved", "rejected", "more_evidence"]
    notes: str = ""


class SqlAlchemyAuditRecorder:
    """Persist workflow completion using the append-only tenant audit chain."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(self, event: dict[str, object]) -> str:
        tenant_id = event.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError("audit event requires a tenant_id")
        with self._session_factory() as session:
            raw_verdicts = event.get("verdicts")
            verdicts = cast(dict[str, Any], raw_verdicts) if isinstance(raw_verdicts, dict) else {}
            stored = append_audit_event(
                session,
                tenant_id=tenant_id,
                event_type="workflow.completed",
                prompt_version=str(event.get("prompt_version", "")),
                verdicts=verdicts,
                payload={
                    key: value
                    for key, value in event.items()
                    if key not in {"tenant_id", "verdicts"}
                },
            )
            return str(stored.id)


def _step_count(state: GraphState, node_name: str) -> int:
    counts = state.get("step_counts", {})
    return counts.get(node_name, 0)


def _run_stage(
    state: GraphState,
    node_name: str,
    stage: PipelineStage,
    allowed_keys: frozenset[str],
    settings: GraphSettings,
) -> GraphState:
    if _step_count(state, node_name) >= settings.max_node_attempts:
        raise RuntimeError(f"workflow node '{node_name}' exceeded its execution cap")
    update = stage(state)
    if not isinstance(update, Mapping):
        raise TypeError(f"workflow stage '{node_name}' must return a mapping")
    unexpected = set(update) - allowed_keys
    if unexpected:
        raise ValueError(
            f"workflow stage '{node_name}' returned disallowed state keys: "
            f"{', '.join(sorted(unexpected))}"
        )
    result = cast(GraphState, dict(update))
    result["step_counts"] = {node_name: 1}
    return result


def _stage_node(
    node_name: str,
    stage: PipelineStage,
    allowed_keys: frozenset[str],
    settings: GraphSettings,
) -> Callable[[GraphState], GraphState]:
    def run(state: GraphState) -> GraphState:
        return _run_stage(state, node_name, stage, allowed_keys, settings)

    return run


def _as_langgraph_node(
    node: Callable[[GraphState], GraphState],
) -> StateNode[GraphState, None]:
    return cast(StateNode[GraphState, None], node)


def _route_node(
    services: WorkflowServices, settings: GraphSettings
) -> Callable[[GraphState], GraphState]:
    def route(state: GraphState) -> GraphState:
        if _step_count(state, "route") >= settings.max_node_attempts:
            raise RuntimeError("workflow node 'route' exceeded its execution cap")
        required_fields = ("job_id", "tenant_id", "thread_id", "assessment_date", "query")
        missing_fields = [name for name in required_fields if name not in state]
        if missing_fields:
            raise ValueError(f"workflow input is missing: {', '.join(missing_fields)}")
        for field in ("job_id", "tenant_id", "thread_id", "query"):
            if not isinstance(state[field], str) or not state[field].strip():
                raise ValueError(f"workflow input '{field}' must be a non-empty string")
        if not isinstance(state["assessment_date"], date):
            raise ValueError("workflow assessment_date must be a date")
        query = state["query"].strip()
        if not query:
            raise ValueError("workflow query must not be empty")
        intent = services.router.route(query).intent
        if intent not in _INTENT_ROUTES:
            raise ValueError(f"router returned an unsupported intent: {intent}")
        return {
            "intent": intent,
            "route": _INTENT_ROUTES[intent],
            "scorecard": None,
            "step_counts": {"route": 1},
        }

    return route


def _next_route(state: GraphState) -> str:
    route = state.get("route")
    if route == "full_analysis":
        return "full_analysis"
    if route == "retrieval_only":
        return "retrieval_only"
    if route == "out_of_scope":
        return "out_of_scope"
    raise ValueError("workflow route node did not produce a valid route")


def _after_retrieval(state: GraphState) -> str:
    route = state.get("route")
    if route == "full_analysis":
        return "verify"
    if route in {"retrieval_only", "out_of_scope"}:
        return "explain_publish"
    raise ValueError("retrieval node received an invalid workflow route")


def _verify_node(
    services: WorkflowServices, settings: GraphSettings
) -> Callable[[GraphState], GraphState]:
    def verify(state: GraphState) -> GraphState:
        if _step_count(state, "verify") >= settings.max_node_attempts:
            raise RuntimeError("workflow node 'verify' exceeded its execution cap")
        claims = state.get("claims", [])
        if not claims:
            raise ValueError("full analysis requires at least one evidence-backed claim")
        context = state.get("verification_context")
        if context is None:
            raise ValueError("full analysis requires a verification context")
        risk = state.get("risk")
        risk_score = risk.p_fail_6m if risk is not None else context.risk_score
        active_context = context.model_copy(update={"risk_score": risk_score})
        verdicts = services.verifier.verify(claims, active_context)
        escalation = services.verifier.escalation_state(
            verdicts,
            risk_score,
            critical_risk_threshold=settings.risk_critical_threshold,
        )
        return {
            "verdicts": verdicts,
            "escalation": escalation,
            "verification_context": active_context,
            "step_counts": {"verify": 1},
        }

    return verify


def _decide_node(settings: GraphSettings) -> Callable[[GraphState], GraphState]:
    def decide(state: GraphState) -> GraphState:
        if _step_count(state, "decide") >= settings.max_node_attempts:
            raise RuntimeError("workflow node 'decide' exceeded its execution cap")
        claims = state.get("claims", [])
        verdicts = state.get("verdicts", [])
        context = state.get("verification_context")
        if not claims or context is None:
            raise ValueError("decision requires claims and a verification context")
        claim_by_id = {claim.claim_id: claim for claim in claims}
        evidence_by_id = {item.evidence_id: item for item in state.get("evidence", [])}
        lines: list[ScorecardLine] = []
        for verdict in verdicts:
            claim = claim_by_id.get(verdict.claim_id)
            if claim is None:
                raise ValueError(f"verdict references unknown claim: {verdict.claim_id}")
            lines.append(
                ScorecardLine(
                    claim=claim,
                    verdict=verdict,
                    evidence=[
                        evidence_by_id[evidence_id]
                        for evidence_id in verdict.evidence_ids
                        if evidence_id in evidence_by_id
                    ],
                )
            )
        risk = state.get("risk")
        risk_score = risk.p_fail_6m if risk is not None else context.risk_score
        escalation = state.get("escalation") or EscalationState()
        if risk_score >= settings.risk_review_threshold and not escalation.is_escalated:
            escalation = EscalationState(
                is_escalated=True,
                priority=(
                    "critical"
                    if risk_score >= settings.risk_critical_threshold
                    else "normal"
                ),
                reason="RISK_FORECAST_REQUIRES_REVIEW",
                details={"risk_score": risk_score},
            )
        has_failure = any(verdict.outcome == "fail" for verdict in verdicts)
        overall_status: Literal["compliant", "non_compliant", "review_required"]
        if escalation.is_escalated:
            overall_status = "review_required"
        elif has_failure:
            overall_status = "non_compliant"
        else:
            overall_status = "compliant"
        scorecard = Scorecard(
            job_id=state["job_id"],
            tenant_id=state["tenant_id"],
            assessment_date=state["assessment_date"],
            overall_status=overall_status,
            risk_score=risk_score,
            lines=lines,
            re_audit_recommended=risk_score >= settings.risk_reaudit_threshold or has_failure,
            summary="",
        )
        return {
            "scorecard": scorecard,
            "escalation": escalation,
            "step_counts": {"decide": 1},
        }

    return decide


def _hitl_node(settings: GraphSettings) -> Callable[[GraphState], GraphState]:
    def wait_for_review(state: GraphState) -> GraphState:
        if _step_count(state, "hitl_wait") >= settings.max_node_attempts:
            raise RuntimeError("workflow node 'hitl_wait' exceeded its execution cap")
        escalation = state.get("escalation")
        update: GraphState = {"step_counts": {"hitl_wait": 1}}
        if escalation is None or not escalation.is_escalated:
            update["review_decision"] = None
            return update
        payload = interrupt(
            {
                "job_id": state["job_id"],
                "tenant_id": state["tenant_id"],
                "priority": escalation.priority,
                "reason": escalation.reason,
                "triggered_by_rule": escalation.triggered_by_rule,
            }
        )
        decision = ReviewDecision.model_validate(payload)
        update["review_decision"] = decision.model_dump()
        return update

    return wait_for_review


def _explain_node(
    services: WorkflowServices, settings: GraphSettings
) -> Callable[[GraphState], GraphState]:
    def explain(state: GraphState) -> GraphState:
        if _step_count(state, "explain_publish") >= settings.max_node_attempts:
            raise RuntimeError("workflow node 'explain_publish' exceeded its execution cap")
        scorecard = state.get("scorecard")
        findings = tuple(
            VerifiedFinding(
                claim_id=verdict.claim_id,
                rule_id=verdict.rule_id,
                outcome=verdict.outcome,
                reason_code=verdict.reason_code,
                evidence_ids=tuple(verdict.evidence_ids),
            )
            for verdict in state.get("verdicts", [])
        )
        context = ExplanationContext(
            overall_status=(
                scorecard.overall_status if scorecard is not None else "informational"
            ),
            findings=findings,
            evidence_ids=tuple(sorted({item for finding in findings for item in finding.evidence_ids})),
            risk_score=scorecard.risk_score if scorecard is not None else None,
        )
        result = services.explainer.summarize(
            context,
            state.get("prompt_version", settings.prompt_version),
        )
        if not isinstance(result, str) or not result.strip():
            raise ValueError("explanation provider must return non-empty text")
        explanation = f"Verified outcome: {context.overall_status}. {result.strip()}"
        return {
            "explanation": explanation,
            "step_counts": {"explain_publish": 1},
        }

    return explain


def _record_node(
    services: WorkflowServices, settings: GraphSettings
) -> Callable[[GraphState], GraphState]:
    def record(state: GraphState) -> GraphState:
        if _step_count(state, "record") >= settings.max_node_attempts:
            raise RuntimeError("workflow node 'record' exceeded its execution cap")
        scorecard = state.get("scorecard")
        event: dict[str, object] = {
            "job_id": state["job_id"],
            "tenant_id": state["tenant_id"],
            "thread_id": state["thread_id"],
            "event_type": "workflow.completed",
            "prompt_version": state.get("prompt_version", settings.prompt_version),
            "overall_status": scorecard.overall_status if scorecard is not None else "informational",
            "verdicts": {
                f"{verdict.claim_id}:{verdict.rule_id}": verdict.outcome
                for verdict in state.get("verdicts", [])
            },
            "review_decision": state.get("review_decision"),
        }
        event_id = services.audit_recorder.record(event)
        if not event_id:
            raise ValueError("audit recorder must return a non-empty event ID")
        return {
            "audit_event_id": event_id,
            "audit_events": [event],
            "step_counts": {"record": 1},
        }

    return record


def build_workflow(
    services: WorkflowServices,
    *,
    checkpointer: Any,
    settings: GraphSettings | None = None,
) -> Any:
    """Compile the graph; callers must provide persistence and every pipeline stage."""
    active_settings = settings or load_graph_settings()
    checkpointer.serde = JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("backend.app.domain.models", model_name) for model_name in _CHECKPOINT_MODELS
        ]
    )
    retry_policy = RetryPolicy(
        initial_interval=0.01,
        backoff_factor=2.0,
        max_interval=0.05,
        max_attempts=active_settings.max_node_attempts,
        jitter=False,
        retry_on=(RetryableWorkflowError, ConnectionError, TimeoutError),
    )
    graph: StateGraph[GraphState, None, GraphState, GraphState] = StateGraph(GraphState)
    graph.add_node("route", _as_langgraph_node(_route_node(services, active_settings)))
    for node_name, handler, allowed_keys in (
        ("redact", services.redact, frozenset({"redacted_pages"})),
        ("extract", services.extract, frozenset({"fields", "claims", "evidence"})),
        ("enrich", services.enrich, frozenset({"evidence", "verification_context"})),
        ("forecast", services.forecast, frozenset({"risk"})),
        ("retrieve", services.retrieve, frozenset({"evidence", "retrieved_context"})),
    ):
        graph.add_node(
            node_name,
            _as_langgraph_node(
                _stage_node(node_name, handler, allowed_keys, active_settings)
            ),
            retry_policy=retry_policy,
        )
    graph.add_node("verify", _as_langgraph_node(_verify_node(services, active_settings)))
    graph.add_node("decide", _as_langgraph_node(_decide_node(active_settings)))
    graph.add_node("hitl_wait", _as_langgraph_node(_hitl_node(active_settings)))
    graph.add_node(
        "explain_publish",
        _as_langgraph_node(_explain_node(services, active_settings)),
        retry_policy=retry_policy,
    )
    graph.add_node(
        "record",
        _as_langgraph_node(_record_node(services, active_settings)),
        retry_policy=retry_policy,
    )
    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        _next_route,
        {
            "full_analysis": "redact",
            "retrieval_only": "retrieve",
            "out_of_scope": "explain_publish",
        },
    )
    graph.add_edge("redact", "extract")
    graph.add_edge("extract", "enrich")
    graph.add_edge("enrich", "forecast")
    graph.add_edge("forecast", "retrieve")
    graph.add_conditional_edges(
        "retrieve",
        _after_retrieval,
        {"verify": "verify", "explain_publish": "explain_publish"},
    )
    graph.add_edge("verify", "decide")
    graph.add_edge("decide", "hitl_wait")
    graph.add_edge("hitl_wait", "explain_publish")
    graph.add_edge("explain_publish", "record")
    graph.add_edge("record", END)
    return graph.compile(checkpointer=checkpointer)


@contextmanager
def postgres_checkpointer(connection_string: str) -> Iterator[PostgresSaver]:
    """Open and initialize PostgreSQL checkpoint storage for durable HITL resumes."""
    if connection_string.startswith("postgresql+psycopg://"):
        connection_string = connection_string.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )
    if not connection_string.startswith(("postgresql://", "postgres://")):
        raise ValueError("checkpoint URL must use PostgreSQL")
    with PostgresSaver.from_conn_string(connection_string) as checkpointer:
        checkpointer.setup()
        yield checkpointer


def invoke_workflow(
    graph: Any,
    initial_state: GraphState,
    *,
    settings: GraphSettings | None = None,
) -> Any:
    """Run a new thread with the configured recursion cap and stable checkpoint key."""
    thread_id = initial_state.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("workflow input requires a non-empty thread_id")
    active_settings = settings or load_graph_settings()
    return graph.invoke(
        initial_state,
        config={
            "configurable": {"thread_id": thread_id},
            "recursion_limit": active_settings.recursion_limit,
        },
    )


def resume_workflow(
    graph: Any,
    *,
    thread_id: str,
    decision: ReviewDecision,
    settings: GraphSettings | None = None,
) -> Any:
    """Resume one paused workflow thread using a validated human decision."""
    if not thread_id:
        raise ValueError("thread_id must not be empty")
    active_settings = settings or load_graph_settings()
    return graph.invoke(
        Command(resume=decision.model_dump()),
        config={
            "configurable": {"thread_id": thread_id},
            "recursion_limit": active_settings.recursion_limit,
        },
    )
