"""JWT authentication primitives and tenant-scoped API principals."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from backend.app.core.config import settings

_password_hasher = PasswordHasher()
_bearer_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/token", auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str
    org_id: str = ""

    def __post_init__(self) -> None:
        if not self.org_id:
            object.__setattr__(self, "org_id", self.tenant_id)


def require_role(*allowed_roles: str):
    """RBAC dependency ensuring the authenticated principal has sufficient permissions."""
    def _role_checker(principal: Principal = Depends(require_principal)) -> Principal:
        if principal.role in {"owner", "admin"}:
            return principal
        if allowed_roles and principal.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: requires one of {allowed_roles}",
            )
        return principal
    return _role_checker


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerificationError:
        return False


def create_access_token(
    *,
    user_id: str,
    tenant_id: str,
    role: str,
    now: datetime | None = None,
) -> tuple[str, int]:
    lifetime_seconds = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    issued_at = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=lifetime_seconds),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, lifetime_seconds


def _demo_principal() -> Principal:
    return Principal(
        user_id=settings.DEMO_USER_ID,
        tenant_id=settings.DEMO_TENANT_ID,
        role="tenant_admin",
    )


async def require_principal(
    token: Annotated[str | None, Depends(_bearer_scheme)],
) -> Principal:
    if not settings.AUTH_ENABLED:
        return _demo_principal()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Check against Supabase JWT secret if configured, otherwise SECRET_KEY
        signing_key = settings.SUPABASE_JWT_SECRET or settings.SECRET_KEY
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        user_id = str(UUID(str(payload["sub"])))
        tenant_id = str(UUID(str(payload.get("tenant_id") or payload.get("org_id") or settings.DEMO_TENANT_ID)))
        role = payload.get("role") or payload.get("app_metadata", {}).get("role", "viewer")
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None
    if not isinstance(role, str) or not role:
        raise unauthorized
    return Principal(user_id=user_id, tenant_id=tenant_id, role=role)


CurrentPrincipal = Annotated[Principal, Depends(require_principal)]
