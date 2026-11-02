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
_bearer_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/token")


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str


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


async def require_principal(
    token: Annotated[str, Depends(_bearer_scheme)],
) -> Principal:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "tenant_id", "role", "exp"]},
        )
        user_id = str(UUID(str(payload["sub"])))
        tenant_id = str(UUID(str(payload["tenant_id"])))
        role = payload["role"]
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None
    if not isinstance(role, str) or not role:
        raise unauthorized
    return Principal(user_id=user_id, tenant_id=tenant_id, role=role)


CurrentPrincipal = Annotated[Principal, Depends(require_principal)]
