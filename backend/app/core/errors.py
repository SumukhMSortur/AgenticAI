"""Application domain and infrastructure exceptions with standard error codes."""

from typing import Any


class EcoChainError(Exception):
    """Base exception for all EcoChain application errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class ValidationError(EcoChainError):
    """Raised when domain entities or input parameters fail validation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="VALIDATION_ERROR", details=details)


class AuthenticationError(EcoChainError):
    """Raised when authentication credentials are missing or invalid."""

    def __init__(self, message: str = "Invalid authentication credentials") -> None:
        super().__init__(message=message, code="AUTH_INVALID")


class AuthorizationError(EcoChainError):
    """Raised when access to a resource across tenant or role boundaries is forbidden."""

    def __init__(self, message: str = "Operation not permitted") -> None:
        super().__init__(message=message, code="AUTH_FORBIDDEN")


class TenantIsolationError(AuthorizationError):
    """Raised when cross-tenant access violation occurs."""

    def __init__(self, message: str = "Access denied: tenant mismatch") -> None:
        super().__init__(message=message)
        self.code = "TENANT_MISMATCH"


class PrivacyViolationError(EcoChainError):
    """Raised when unredacted PII or unauthorized payloads attempt egress."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="PRIVACY_LEAKAGE_DETECTED", details=details)


class AuditChainTamperError(EcoChainError):
    """Raised when the hash-chain integrity of the append-only audit log fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="AUDIT_CHAIN_CORRUPTED", details=details)


class ResourceNotFoundError(EcoChainError):
    """Raised when requested entity is not found."""

    def __init__(self, entity: str, identifier: str) -> None:
        super().__init__(
            message=f"{entity} with id '{identifier}' not found",
            code="NOT_FOUND",
            details={"entity": entity, "id": identifier},
        )
