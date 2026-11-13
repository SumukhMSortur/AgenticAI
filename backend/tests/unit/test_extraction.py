"""Unit tests for document field extraction, normalizers, and LayoutLMv3 adapter."""

import json
from pathlib import Path

from backend.app.extraction.heuristic import HeuristicExtractor
from backend.app.extraction.layoutlmv3 import LayoutLMv3Extractor
from backend.app.extraction.normalizers import (
    normalize_date,
    normalize_issuer,
    normalize_materials,
)


def test_normalizers_dates() -> None:
    """Verifies that dates normalize to standard ISO format."""
    assert normalize_date("2026-11-02") == "2026-11-02"
    assert (
        normalize_date("02/11/2026") == "2026-02-11" or normalize_date("02/11/2026") == "2026-11-02"
    )
    assert normalize_date("November 2, 2026") == "2026-11-02"
    assert normalize_date("invalid_date_text") is None


def test_normalizers_issuers() -> None:
    """Verifies that issuer legal entity suffixes are cleaned and canonicalized."""
    assert normalize_issuer("Control Union Certifications B.V.") == "control union certifications"
    assert normalize_issuer("OEKO-TEX Association (Service GmbH)") == "oeko tex"
    assert normalize_issuer("Ecocert Greenlife S.A.S.") == "ecocert greenlife"


def test_normalizers_materials() -> None:
    """Verifies parsing of textile material percentages and taxonomy tags."""
    res1 = normalize_materials("100% Organic Cotton")
    assert len(res1) == 1
    assert res1[0]["percentage"] == 100
    assert res1[0]["taxonomy"]["code"] == "CO-ORG"

    res2 = normalize_materials("80% Organic Cotton, 20% Recycled Polyester")
    assert len(res2) == 2
    assert res2[0]["percentage"] == 80
    assert res2[0]["taxonomy"]["code"] == "CO-ORG"
    assert res2[1]["percentage"] == 20
    assert res2[1]["taxonomy"]["code"] == "PES-REC"


def test_heuristic_extractor_fields() -> None:
    """Verifies that HeuristicExtractor extracts fields from a sample synthetic PDF."""
    sample_pdf = Path("data/synthetic/documents/DOC-CLN-0001.pdf")
    if not sample_pdf.exists():
        return

    extractor = HeuristicExtractor()
    fields = extractor.extract(sample_pdf, "DOC-CLN-0001", "mock_hash_001")

    field_map = {f.name: f for f in fields}
    assert "certificate_type" in field_map
    assert "issuer" in field_map
    assert "valid_to" in field_map
    assert "scope_materials" in field_map

    # Check bbox and confidence
    for f in fields:
        assert f.bbox is not None
        assert 0 <= f.bbox.x0 <= f.bbox.x1 <= 1000
        assert f.confidence >= 0.90


def test_layoutlm_fallback() -> None:
    """Verifies LayoutLMv3Extractor gracefully falls back to HeuristicExtractor when weights are absent."""
    extractor = LayoutLMv3Extractor(weights_path="nonexistent/path/to/weights")
    assert extractor.model_loaded is False

    sample_pdf = Path("data/synthetic/documents/DOC-CLN-0001.pdf")
    if not sample_pdf.exists():
        return

    fields = extractor.extract(sample_pdf, "DOC-CLN-0001", "mock_hash_001")
    assert len(fields) >= 5


def test_extraction_report_metrics() -> None:
    """Verifies reports/extraction.json exists and meets evaluation gates."""
    report_path = Path("reports/extraction.json")
    assert report_path.exists(), "reports/extraction.json not found."

    with open(report_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data["macro_f1"] >= 0.85
    assert data["is_gate_passed"] is True
    assert "per_field_metrics" in data
