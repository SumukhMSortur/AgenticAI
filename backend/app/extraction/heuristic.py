"""Heuristic rule-based extractor using OCR text and layout spatial coordinates."""

import re
from pathlib import Path
from typing import Any

import pymupdf

from backend.app.domain.models import BBox, ExtractedField
from backend.app.extraction.base import Extractor
from backend.app.extraction.normalizers import normalize_date


class HeuristicExtractor(Extractor):
    """Working default and test double extractor utilizing regex layout rules and PyMuPDF."""

    def __init__(self) -> None:
        self.field_patterns = {
            "issuer": re.compile(
                r"(?i)(?:Certification Body|Issuer|Authorized Body):\s*([^\n\r]+)"
            ),
            "facility_id": re.compile(
                r"(?i)(?:Applicant Facility ID|Facility ID|Facility):\s*([A-Za-z0-9\-_]+)"
            ),
            "supplier_id": re.compile(r"(?i)(?:Supplier ID|Vendor ID):\s*([A-Za-z0-9\-_]+)"),
            "valid_from": re.compile(
                r"(?i)(?:Valid From|Issue Date|Issued):\s*([A-Za-z0-9\-\s,]+)"
            ),
            "valid_to": re.compile(r"(?i)(?:Valid To|Expiry Date|Expires):\s*([A-Za-z0-9\-\s,]+)"),
            "scope_materials": re.compile(
                r"(?i)(?:Certified Product Category \/ Material Scope|Scope|Certified Material Scope):\s*([^\n\r]+)"
            ),
        }

    def extract(self, doc_path: Path, doc_id: str, doc_hash: str) -> list[ExtractedField]:
        doc: Any = pymupdf.open(str(doc_path))
        extracted_fields: list[ExtractedField] = []

        try:
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                width = float(page.rect.width or 595.0)
                height = float(page.rect.height or 842.0)
                full_text = str(page.get_text())

                # Check certificate type specifically
                cert_type_val = "Standard Certificate"
                cert_search_term = "CERTIFICATE"
                if "GOTS" in full_text.upper():
                    cert_type_val = "GOTS"
                    cert_search_term = "GOTS"
                elif "OEKO-TEX" in full_text.upper():
                    cert_type_val = "OEKO-TEX"
                    cert_search_term = "OEKO-TEX"

                rects = page.search_for(cert_search_term)
                if rects:
                    r = rects[0]
                    box = BBox(
                        x0=max(0, min(1000, int(round((r.x0 / width) * 1000)))),
                        y0=max(0, min(1000, int(round((r.y0 / height) * 1000)))),
                        x1=max(0, min(1000, int(round((r.x1 / width) * 1000)))),
                        y1=max(0, min(1000, int(round((r.y1 / height) * 1000)))),
                    )
                else:
                    box = BBox(x0=160, y0=60, x1=420, y1=100)

                extracted_fields.append(
                    ExtractedField(
                        name="certificate_type",
                        value=cert_type_val,
                        doc_id=doc_id,
                        doc_hash=doc_hash,
                        page=page_idx + 1,
                        bbox=box,
                        confidence=0.99,
                    )
                )

                # Match other field patterns
                for field_name, pattern in self.field_patterns.items():
                    match = pattern.search(full_text)
                    if match:
                        raw_val = match.group(1).strip()
                        # Clean leading bullet points or symbols
                        raw_val = re.sub(r"^[•\-\*\s]+", "", raw_val).strip()

                        # Normalize dates if applicable
                        if "valid" in field_name:
                            parsed_date = normalize_date(raw_val)
                            final_val: str | None = parsed_date or raw_val
                        else:
                            final_val = raw_val

                        # Find bounding box using text search on page
                        rects = page.search_for(match.group(0)[:30])
                        if rects:
                            r = rects[0]
                            box = BBox(
                                x0=max(0, min(1000, int(round((r.x0 / width) * 1000)))),
                                y0=max(0, min(1000, int(round((r.y0 / height) * 1000)))),
                                x1=max(0, min(1000, int(round((r.x1 / width) * 1000)))),
                                y1=max(0, min(1000, int(round((r.y1 / height) * 1000)))),
                            )
                        else:
                            box = BBox(
                                x0=50,
                                y0=100 + len(extracted_fields) * 40,
                                x1=500,
                                y1=130 + len(extracted_fields) * 40,
                            )

                        extracted_fields.append(
                            ExtractedField(
                                name=field_name,
                                value=final_val,
                                doc_id=doc_id,
                                doc_hash=doc_hash,
                                page=page_idx + 1,
                                bbox=box,
                                confidence=0.98,
                            )
                        )
        finally:
            doc.close()

        return extracted_fields
