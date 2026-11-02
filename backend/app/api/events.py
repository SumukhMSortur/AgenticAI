"""Tenant-authorized Redis Streams event publication and SSE replay."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from sse_starlette.event import ServerSentEvent

_STREAM_ID_PATTERN = re.compile(r"^\d+-\d+$")
_TERMINAL_EVENTS = {"completed", "failed"}


def validate_stream_id(stream_id: str | None) -> None:
    if stream_id is not None and not _STREAM_ID_PATTERN.fullmatch(stream_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Last-Event-ID must be a Redis stream ID",
        )


def _stream_id_tuple(stream_id: str) -> tuple[int, int]:
    milliseconds, sequence = stream_id.split("-", maxsplit=1)
    return int(milliseconds), int(sequence)


async def _cursor_has_seen_terminal_event(redis: Redis, stream: str, cursor: str) -> bool:
    latest = await redis.xrevrange(stream, max="+", min="-", count=1)
    if not latest:
        return False
    latest_id, fields = latest[0]
    latest_id = latest_id.decode() if isinstance(latest_id, bytes) else latest_id
    raw_type = fields.get(b"event_type", fields.get("event_type", b""))
    latest_type = raw_type.decode() if isinstance(raw_type, bytes) else raw_type
    return (
        latest_type in _TERMINAL_EVENTS
        and _stream_id_tuple(cursor) >= _stream_id_tuple(latest_id)
    )


def job_stream_key(job_id: str) -> str:
    return f"ecochain:job:{job_id}:events"


async def publish_job_event(
    redis: Redis,
    job_id: str,
    event_type: str,
    summary: str,
    *,
    step: str | None = None,
) -> str:
    event_data: dict[str, str] = {
        "job_id": job_id,
        "event_type": event_type,
        "summary": summary,
    }
    if step is not None:
        event_data["step"] = step
    entry_id = await redis.xadd(
        job_stream_key(job_id),
        {"event_type": event_type, "data": json.dumps(event_data, separators=(",", ":"))},
        maxlen=1000,
        approximate=True,
    )
    return entry_id.decode() if isinstance(entry_id, bytes) else entry_id


async def stream_job_events(
    request: Request,
    redis: Redis,
    job_id: str,
    last_event_id: str | None,
) -> AsyncIterator[ServerSentEvent]:
    cursor = last_event_id or "0-0"
    validate_stream_id(last_event_id)
    stream = job_stream_key(job_id)
    while not await request.is_disconnected():
        if await _cursor_has_seen_terminal_event(redis, stream, cursor):
            return
        batches = await redis.xread({stream: cursor}, count=100, block=5000)
        if not batches:
            await asyncio.sleep(0)
            continue
        for _stream_name, entries in batches:
            for entry_id, fields in entries:
                cursor = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                raw_data = fields.get(b"data", fields.get("data"))
                event_type = fields.get(b"event_type", fields.get("event_type", b"step"))
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode()
                if isinstance(event_type, bytes):
                    event_type = event_type.decode()
                event_data: Any = json.loads(raw_data)
                yield ServerSentEvent(
                    id=cursor,
                    event=str(event_type),
                    data=json.dumps(event_data, separators=(",", ":")),
                )
                if event_type in _TERMINAL_EVENTS:
                    return
