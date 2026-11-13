"""PostgreSQL process/container restart and golden-set integration coverage."""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import settings
from backend.app.db.audit_log import append_audit_event, verify_chain
from backend.app.db.models import AuditEvent
from backend.app.domain.models import EvidenceItem, GraphState
from backend.app.graph.workflow import (
    ReviewDecision,
    build_workflow,
    invoke_workflow,
    load_graph_settings,
    postgres_checkpointer,
    resume_workflow,
)
from backend.tests.integration.graph_postgres_worker import (
    _case_inputs,
    _services,
    load_golden_cases,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE_FILE = _PROJECT_ROOT / "docker" / "compose.dev.yml"
_ENV_FILE = _PROJECT_ROOT / ".env"


def _postgres_url() -> str:
    value = os.environ.get("ECOCHAIN_TEST_POSTGRES_URL") or settings.TEST_DATABASE_URL
    if not value:
        pytest.skip("Set TEST_DATABASE_URL or ECOCHAIN_TEST_POSTGRES_URL for PostgreSQL coverage.")
    parsed = urlsplit(value)
    if (
        parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.port != 5432
        or parsed.path != "/ecochain_test"
    ):
        pytest.fail(
            "Phase 9 durable integration requires the local Compose "
            "ecochain_test database at localhost:5432."
        )
    return value


def _read_lines(pipe: TextIO, output: queue.Queue[str | None]) -> None:
    try:
        for line in pipe:
            output.put(line.rstrip("\r\n"))
    finally:
        output.put(None)


def _wait_for_child_prefix(
    process: subprocess.Popen[str],
    output: queue.Queue[str | None],
    prefix: str,
    timeout: float = 60.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    observed: list[str] = []
    while time.monotonic() < deadline:
        try:
            line = output.get(timeout=0.1)
        except queue.Empty:
            if process.poll() is not None:
                time.sleep(0.2)
                while True:
                    try:
                        remaining = output.get_nowait()
                    except queue.Empty:
                        break
                    if remaining is None:
                        break
                    observed.append(remaining)
                break
            continue
        if line is None:
            break
        observed.append(line)
        if line.startswith(prefix):
            payload = json.loads(line[len(prefix) :])
            if not isinstance(payload, dict):
                raise AssertionError(f"Child process returned invalid {prefix} payload.")
            return payload
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
    raise AssertionError(f"Child did not emit {prefix!r}; output: {' | '.join(observed[-20:])}")


def _start_child(
    mode: str,
    connection_string: str,
    thread_id: str,
    tenant_id: str,
    case_id: str,
) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(_PROJECT_ROOT)
        if not existing_pythonpath
        else str(_PROJECT_ROOT) + os.pathsep + existing_pythonpath
    )
    environment["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "backend.tests.integration.graph_postgres_worker",
            mode,
            connection_string,
            thread_id,
            tenant_id,
            case_id,
        ],
        cwd=_PROJECT_ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def _restart_postgres_container() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("Docker CLI is required for the PostgreSQL container-restart gate.")
    compose = [
        docker,
        "compose",
        "--env-file",
        str(_ENV_FILE),
        "-f",
        str(_COMPOSE_FILE),
    ]
    subprocess.run(
        [*compose, "restart", "postgres"],
        cwd=_PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    subprocess.run(
        [*compose, "up", "-d", "--wait", "postgres"],
        cwd=_PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _audit_rows(connection_string: str, tenant_id: str) -> list[AuditEvent]:
    engine = create_engine(connection_string, pool_pre_ping=True)
    factory = sessionmaker(bind=engine)
    try:
        with factory() as session:
            rows = list(
                session.execute(
                    select(AuditEvent)
                    .where(AuditEvent.tenant_id == tenant_id)
                    .order_by(AuditEvent.sequence)
                ).scalars()
            )
            valid, reason = verify_chain(session, tenant_id)
            assert valid, reason
            return rows
    finally:
        engine.dispose()


@pytest.mark.integration
def test_postgres_checkpoint_survives_process_and_container_restart() -> None:
    connection_string = _postgres_url()
    case = next(case for case in load_golden_cases() if case["expected_escalation"])
    tenant_id = str(uuid.uuid4())
    thread_id = f"restart-{uuid.uuid4().hex}"
    child = _start_child(
        "pause",
        connection_string,
        thread_id,
        tenant_id,
        case["case_id"],
    )
    output: queue.Queue[str | None] = queue.Queue()
    assert child.stdout is not None
    reader = threading.Thread(
        target=_read_lines,
        args=(child.stdout, output),
        daemon=True,
    )
    reader.start()
    try:
        paused = _wait_for_child_prefix(child, output, "PAUSED:")
        assert paused["thread_id"] == thread_id
        assert paused["interrupt"] is True
        child.terminate()
        child.wait(timeout=10)
        assert child.returncode is not None
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        if child.stdin is not None:
            child.stdin.close()
        reader.join(timeout=10)

    _restart_postgres_container()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.tests.integration.graph_postgres_worker",
            "resume",
            connection_string,
            thread_id,
            tenant_id,
            case["case_id"],
        ],
        cwd=_PROJECT_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(_PROJECT_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
            "PYTHONUNBUFFERED": "1",
        },
        input="",
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )

    result_line = next(
        line for line in completed.stdout.splitlines() if line.startswith("RESUMED:")
    )
    resumed = json.loads(result_line[len("RESUMED:") :])
    assert resumed["thread_id"] == thread_id
    assert resumed["overall_status"] == case["expected_overall_status"]
    expected_verdicts = {
        row["rule_id"]: row["expected_outcome"] for row in case["expected_verdicts"]
    }
    assert all(
        resumed["verdicts"].get(rule_id) == outcome
        for rule_id, outcome in expected_verdicts.items()
    )
    rows = _audit_rows(connection_string, tenant_id)
    assert len(rows) == 1
    assert rows[0].event_type == "workflow.completed"
    assert rows[0].payload is not None
    assert rows[0].payload["review_decision"]["decision"] == "approved"
    assert rows[0].verdicts is not None
    assert all(
        rows[0].verdicts.get(f"{case['case_id']}:{rule_id}") == outcome
        for rule_id, outcome in expected_verdicts.items()
    )


@pytest.mark.integration
def test_postgres_checkpoint_runs_full_golden_set() -> None:
    connection_string = _postgres_url()
    cases = load_golden_cases()
    tenant_id = str(uuid.uuid4())
    engine = create_engine(connection_string, pool_pre_ping=True)
    recorder_factory = sessionmaker(bind=engine)
    try:
        services = _services(connection_string, recorder_factory=recorder_factory)
        with postgres_checkpointer(connection_string) as checkpointer:
            graph = build_workflow(
                services,
                checkpointer=checkpointer,
                settings=load_graph_settings(),
            )
            for case in cases:
                thread_id = f"golden-{uuid.uuid4().hex}-{case['case_id']}"
                claim, context = _case_inputs(case)
                evidence = EvidenceItem(
                    evidence_id=claim.evidence_ids[0],
                    kind="extracted_field",
                    ref={"doc_id": claim.doc_id, "page": claim.page},
                )
                state: GraphState = {
                    "job_id": case["case_id"],
                    "tenant_id": tenant_id,
                    "thread_id": thread_id,
                    "assessment_date": context.assessment_date,
                    "query": case["description"],
                    "claims": [claim],
                    "evidence": [evidence],
                    "verification_context": context,
                    "step_counts": {},
                    "prompt_version": "postgres-golden-v1",
                }
                result = invoke_workflow(graph, state)
                if result.get("__interrupt__"):
                    result = resume_workflow(
                        graph,
                        thread_id=thread_id,
                        decision=ReviewDecision(
                            reviewer_id="postgres-golden-reviewer",
                            decision="approved",
                            notes="Resolve golden integration escalation.",
                        ),
                    )

                actual_verdicts = {
                    verdict.rule_id: verdict.outcome for verdict in result["verdicts"]
                }
                expected_verdicts = {
                    row["rule_id"]: row["expected_outcome"] for row in case["expected_verdicts"]
                }
                assert all(
                    actual_verdicts.get(rule_id) == outcome
                    for rule_id, outcome in expected_verdicts.items()
                ), case["case_id"]
                assert result["escalation"].is_escalated is case["expected_escalation"], case[
                    "case_id"
                ]
                assert result["scorecard"].overall_status == case["expected_overall_status"], case[
                    "case_id"
                ]
                assert result["audit_event_id"]

        rows = _audit_rows(connection_string, tenant_id)
        assert len(rows) == len(cases)
        assert all(row.event_type == "workflow.completed" for row in rows)
    finally:
        engine.dispose()


@pytest.mark.integration
def test_postgres_audit_events_are_append_only() -> None:
    engine = create_engine(_postgres_url(), pool_pre_ping=True)
    tenant_id = str(uuid.uuid4())
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with session_factory() as session:
            event = append_audit_event(
                session,
                tenant_id=tenant_id,
                event_type="integration.audit-immutability",
                payload={"test": True},
            )
            with pytest.raises(DBAPIError, match="audit_events is append-only"):
                session.execute(
                    text("UPDATE audit_events SET event_type = :event_type WHERE id = :event_id"),
                    {"event_type": "tampered", "event_id": event.id},
                )
            session.rollback()

            with pytest.raises(DBAPIError, match="audit_events is append-only"):
                session.execute(
                    text("DELETE FROM audit_events WHERE id = :event_id"),
                    {"event_id": event.id},
                )
            session.rollback()
            assert verify_chain(session, tenant_id) == (True, None)

            session.add(
                AuditEvent(
                    tenant_id=tenant_id,
                    sequence=event.sequence + 1,
                    event_type="integration.audit-tamper",
                    prev_hash=event.event_hash,
                    event_hash="f" * 64,
                    payload={"tampered": True},
                )
            )
            session.commit()
            valid, reason = verify_chain(session, tenant_id)
            assert valid is False
            assert reason is not None
            assert "Payload tampering detected" in reason
    finally:
        engine.dispose()
