"""Focused tests for API authentication, upload validation, and event cursors."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import jwt
import pymupdf
import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.datastructures import UploadFile as StarletteUploadFile

from backend.app.api.events import validate_stream_id
from backend.app.api.security import (
    create_access_token,
    hash_password,
    require_principal,
    verify_password,
)
from backend.app.api.uploads import validate_upload, validate_upload_batch
from backend.app.core.config import settings


def _pdf(page_count: int = 1) -> bytes:
    document = pymupdf.open()
    for _ in range(page_count):
        document.new_page()
    content = document.tobytes()
    document.close()
    return content


def _upload(
    content: bytes,
    *,
    filename: str = "certificate.pdf",
    content_type: str = "application/pdf",
) -> StarletteUploadFile:
    return StarletteUploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.asyncio
async def test_password_hash_and_jwt_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "a" * 64)
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    password_hash = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("incorrect", password_hash)
    token, expires_in = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="auditor",
    )
    principal = await require_principal(token)

    assert principal.user_id == user_id
    assert principal.tenant_id == tenant_id
    assert principal.role == "auditor"
    assert expires_in == settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60


@pytest.mark.asyncio
async def test_expired_jwt_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "b" * 64)
    expired = datetime.now(UTC) - timedelta(minutes=5)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            "role": "auditor",
            "exp": expired,
        },
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    with pytest.raises(HTTPException) as error:
        await require_principal(token)

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_pdf_validation_checks_magic_pages_and_batch_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAX_UPLOAD_PAGES", 2)
    content = _pdf()
    first = await validate_upload(_upload(content), settings.MAX_UPLOAD_SIZE_BYTES)
    duplicate = await validate_upload(_upload(content), settings.MAX_UPLOAD_SIZE_BYTES)
    deduplicated = await validate_upload_batch([_upload(content), _upload(content)])

    assert first.doc_hash == duplicate.doc_hash
    assert len(deduplicated) == 1
    assert deduplicated[0].page_count == 1
    assert deduplicated[0].filename == "certificate.pdf"


@pytest.mark.asyncio
async def test_pdf_validation_rejects_bad_type_signature_and_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HTTPException) as wrong_type:
        await validate_upload(
            _upload(b"not a pdf", content_type="text/plain"),
            settings.MAX_UPLOAD_SIZE_BYTES,
        )
    assert wrong_type.value.status_code == 415

    with pytest.raises(HTTPException) as bad_signature:
        await validate_upload(_upload(b"not a pdf"), settings.MAX_UPLOAD_SIZE_BYTES)
    assert bad_signature.value.status_code == 400

    monkeypatch.setattr(settings, "MAX_UPLOAD_PAGES", 1)
    with pytest.raises(HTTPException) as page_limit:
        await validate_upload(_upload(_pdf(2)), settings.MAX_UPLOAD_SIZE_BYTES)
    assert page_limit.value.status_code == 413


@pytest.mark.asyncio
async def test_pdf_validation_enforces_size_limit() -> None:
    with pytest.raises(HTTPException) as error:
        await validate_upload(_upload(_pdf()), 8)
    assert error.value.status_code == 413


def test_event_cursor_must_be_a_redis_stream_id() -> None:
    validate_stream_id(None)
    validate_stream_id("1710000000000-1")

    with pytest.raises(HTTPException) as error:
        validate_stream_id("not-a-stream-id")
    assert error.value.status_code == 400
