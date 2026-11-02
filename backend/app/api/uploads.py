"""Bounded PDF validation before document persistence."""

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePath

import pymupdf
from fastapi import HTTPException, UploadFile, status

from backend.app.core.config import settings


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    content: bytes
    doc_hash: str
    page_count: int


def _safe_filename(filename: str | None) -> str:
    leaf = PurePath((filename or "document.pdf").replace("\\", "/")).name
    normalized = re.sub(r"[^A-Za-z0-9._ -]", "_", leaf).strip(" .")
    if not normalized:
        normalized = "document.pdf"
    return normalized[:255]


async def validate_upload(upload: UploadFile, remaining_bytes: int) -> ValidatedUpload:
    if upload.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only application/pdf uploads are accepted",
        )
    content = await upload.read(remaining_bytes + 1)
    if len(content) > remaining_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Upload size limit exceeded",
        )
    if not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file does not have a PDF signature",
        )
    try:
        document = pymupdf.open(stream=content, filetype="pdf")  # type: ignore[no-untyped-call]
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed PDF document",
        ) from exc
    try:
        if document.is_encrypted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password-protected PDFs are not supported",
            )
        page_count = document.page_count
    finally:
        document.close()  # type: ignore[no-untyped-call]
    if page_count < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF must contain at least one page",
        )
    if page_count > settings.MAX_UPLOAD_PAGES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="PDF page limit exceeded",
        )
    return ValidatedUpload(
        filename=_safe_filename(upload.filename),
        content=content,
        doc_hash=sha256(content).hexdigest(),
        page_count=page_count,
    )


async def validate_upload_batch(uploads: list[UploadFile]) -> list[ValidatedUpload]:
    if not uploads:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one PDF is required",
        )
    if len(uploads) > settings.MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Maximum upload file count exceeded",
        )
    total_bytes = 0
    validated: dict[str, ValidatedUpload] = {}
    for upload in uploads:
        remaining = settings.MAX_UPLOAD_SIZE_BYTES - total_bytes
        if remaining <= 0:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Upload size limit exceeded",
            )
        document = await validate_upload(upload, remaining)
        total_bytes += len(document.content)
        validated.setdefault(document.doc_hash, document)
    return list(validated.values())
