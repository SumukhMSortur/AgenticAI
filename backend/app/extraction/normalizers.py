"""Field normalizers for dates, certification issuers, and material taxonomy."""

import re
from datetime import datetime
from typing import Any

from dateutil import parser as date_parser

# Material taxonomy mapping canonical fiber types
FIBER_TAXONOMY = {
    "organic cotton": {"fiber": "cotton", "attribute": "organic", "code": "CO-ORG"},
    "cotton": {"fiber": "cotton", "attribute": "conventional", "code": "CO-CONV"},
    "recycled polyester": {"fiber": "polyester", "attribute": "recycled", "code": "PES-REC"},
    "polyester": {"fiber": "polyester", "attribute": "conventional", "code": "PES-CONV"},
    "elastane": {"fiber": "elastane", "attribute": "conventional", "code": "EA-CONV"},
    "spandex": {"fiber": "elastane", "attribute": "conventional", "code": "EA-CONV"},
    "viscose": {"fiber": "viscose", "attribute": "conventional", "code": "CV-CONV"},
    "linen": {"fiber": "linen", "attribute": "conventional", "code": "LI-CONV"},
    "wool": {"fiber": "wool", "attribute": "conventional", "code": "WO-CONV"},
}


def normalize_date(date_str: str | None) -> str | None:
    """Parses various date string representations into standard ISO YYYY-MM-DD."""
    if not date_str:
        return None

    clean = date_str.strip()
    # Try direct ISO match first
    if re.match(r"^\d{4}-\d{2}-\d{2}$", clean):
        return clean

    try:
        parsed: datetime = date_parser.parse(clean, fuzzy=True)
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        return None


def normalize_issuer(issuer_str: str | None) -> str:
    """Canonicalizes certificate issuer names by removing legal entity suffixes and whitespace."""
    if not issuer_str:
        return ""

    text = issuer_str.strip().lower()
    # Remove common legal entity designations
    suffixes = [
        r"\bb\.?v\.?\b",
        r"\bgmbh\b",
        r"\bs\.?a\.?s\.?\b",
        r"\bs\.?a\.?\b",
        r"\bplc\b",
        r"\bltd\.?\b",
        r"\binc\.?\b",
        r"\bcorp\.?\b",
        r"\bassociation\b",
        r"\bservice\b",
        r"\bgroup\b",
    ]
    for s in suffixes:
        text = re.sub(s, "", text)

    # Clean non-alphanumeric chars
    cleaned = re.sub(r"[^\w\s]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_materials(materials_raw: str | list[str] | None) -> list[dict[str, Any]]:
    """Parses material composition strings into structured percentage and taxonomy items."""
    if not materials_raw:
        return []

    raw_items = [materials_raw] if isinstance(materials_raw, str) else materials_raw
    parsed_items: list[dict[str, Any]] = []

    percent_pattern = re.compile(r"(\d{1,3})\s*%\s*([a-zA-Z\s]+)")

    for raw_line in raw_items:
        # Split by comma or semicolon if multiple items in line
        segments = re.split(r"[,;•\n]", raw_line)
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue

            match = percent_pattern.search(seg)
            if match:
                percentage = int(match.group(1))
                fiber_name = match.group(2).strip().lower()
            else:
                percentage = 100
                fiber_name = seg.lower()

            # Taxonomy match
            taxonomy_info = None
            for key, val in FIBER_TAXONOMY.items():
                if key in fiber_name:
                    taxonomy_info = val
                    break

            parsed_items.append(
                {
                    "raw_text": seg,
                    "percentage": percentage,
                    "fiber_name": fiber_name,
                    "taxonomy": taxonomy_info,
                }
            )

    return parsed_items
