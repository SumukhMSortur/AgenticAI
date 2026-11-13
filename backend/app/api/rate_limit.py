"""Atomic Redis-backed request rate limiting."""

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.app.api.security import require_principal
from backend.app.core.config import settings


async def enforce_rate_limit(request: Request) -> None:
    redis: Redis | None = getattr(request.app.state, "redis", None)
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiting service is unavailable",
        )
    principal = None
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        try:
            principal = await require_principal(authorization[7:].strip())
        except HTTPException:
            principal = None
    identity = (
        f"{principal.tenant_id}:{principal.user_id}"
        if principal is not None
        else (request.client.host if request.client else "unknown-client")
    )
    key = f"ecochain:rate:{identity}"
    try:
        async with redis.pipeline(transaction=True) as pipeline:
            pipeline.incr(key)
            pipeline.pexpire(
                key,
                settings.API_RATE_LIMIT_WINDOW_SECONDS * 1000,
                nx=True,
            )
            results = await pipeline.execute()
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiting service is unavailable",
        ) from exc
    count = results[0]
    if int(count) > settings.API_RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Request rate limit exceeded",
            headers={"Retry-After": str(settings.API_RATE_LIMIT_WINDOW_SECONDS)},
        )
