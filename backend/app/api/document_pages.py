"""Tenant-bound PDF page rendering."""

from pathlib import Path
from typing import Any, cast

import pymupdf


def render_pdf_page(
    storage_path: str,
    upload_root: Path,
    tenant_id: str,
    page_number: int,
) -> bytes:
    """Render one PDF page after verifying its resolved path is inside the tenant directory."""
    tenant_root = (upload_root / tenant_id).resolve()
    pdf_path = Path(storage_path).resolve()
    if not pdf_path.is_relative_to(tenant_root):
        raise PermissionError("Document storage path is outside the tenant upload directory")
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Document file is unavailable: {pdf_path.name}")

    open_pdf = cast(Any, pymupdf.open)
    matrix_type = cast(Any, pymupdf.Matrix)
    with open_pdf(str(pdf_path)) as document:
        if page_number < 1 or page_number > document.page_count:
            raise IndexError("Requested PDF page does not exist")
        page = document.load_page(page_number - 1)
        pixmap = page.get_pixmap(matrix=matrix_type(2, 2), alpha=False)
        return cast(bytes, pixmap.tobytes("png"))
