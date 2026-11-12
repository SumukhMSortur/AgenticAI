"""Unit tests for Phase 2 dataset integrity, schemas, and reproducibility."""

import json
from pathlib import Path

import pymupdf

from scripts import generate_documents
from scripts.generate_synthetic_data import verify_manifest


def test_manifest_reproducibility() -> None:
    """Verifies that generated files byte-identically match data/MANIFEST.json."""
    assert verify_manifest() is True


def test_audit_histories_schema_and_split() -> None:
    """Verifies 450 factories across splits with 36 months of sequence signals."""
    train_path = Path("data/synthetic/audit_histories_train.json")
    val_path = Path("data/synthetic/audit_histories_val.json")
    test_path = Path("data/synthetic/audit_histories_test.json")

    with open(train_path, encoding="utf-8") as f:
        train_data = json.load(f)
    with open(val_path, encoding="utf-8") as f:
        val_data = json.load(f)
    with open(test_path, encoding="utf-8") as f:
        test_data = json.load(f)

    total_factories = (
        len(train_data["factories"]) + len(val_data["factories"]) + len(test_data["factories"])
    )
    assert total_factories == 450

    # Test individual factory sequence structure
    sample_factory = train_data["factories"][0]
    assert "factory_id" in sample_factory
    assert "will_fail_next_6m" in sample_factory
    assert 0.0 <= sample_factory["p_fail_6m"] <= 1.0
    assert len(sample_factory["history"]) == 36

    sample_month = sample_factory["history"][0]
    required_signals = [
        "carbon_intensity",
        "labor_violations",
        "cert_lapse_days",
        "corrective_action_backlog",
        "safety_incidents",
    ]
    for sig in required_signals:
        assert sig in sample_month


def test_documents_and_annotations() -> None:
    """Verifies generated documents contain valid bboxes and embedded privacy seeds."""
    ann_path = Path("data/synthetic/documents_v2/annotations.json")
    with open(ann_path, encoding="utf-8") as f:
        annotations = json.load(f)

    assert len(annotations) == 480  # 320 clean + 160 adversarial
    assert {
        "certificate",
        "bill_of_materials",
        "invoice",
        "chemical_test_report",
    }.issubset({doc["doc_type"] for doc in annotations})
    adversarial_kinds = {
        doc["adversarial_kind"] for doc in annotations if doc["category"] == "adversarial"
    }
    assert {
        "expired_certificate",
        "unapproved_issuer",
        "scope_mismatch",
        "missing_page",
        "conflicting_supplier_ids",
        "forged_looking_issuer",
    }.issubset(adversarial_kinds)
    assert any(doc["page_count"] > 1 for doc in annotations)
    assert any(doc["visual_variants"]["scan_noise"] for doc in annotations)
    assert any(doc["visual_variants"]["skew_degrees"] != 0 for doc in annotations)
    type_markers = {
        "certificate": "CERTIFICATE OF COMPLIANCE",
        "bill_of_materials": "BILL OF MATERIALS",
        "invoice": "SUPPLIER INVOICE",
        "chemical_test_report": "CHEMICAL TEST REPORT",
    }
    for doc_type, marker in type_markers.items():
        doc_info = next(doc for doc in annotations if doc["doc_type"] == doc_type)
        with pymupdf.open(Path("data/synthetic/documents_v2") / doc_info["filename"]) as pdf:
            assert marker in pdf[0].get_text()

    missing_page = next(doc for doc in annotations if doc.get("adversarial_kind") == "missing_page")
    assert missing_page["missing_pages"] == [2]
    assert missing_page["expected_page_count"] > missing_page["page_count"]
    conflict = next(
        doc
        for doc in annotations
        if doc.get("adversarial_kind") == "conflicting_supplier_ids"
    )
    assert len([field for field in conflict["fields"] if field["name"] == "supplier_id"]) >= 2

    for doc in annotations:
        assert doc["doc_hash"]
        assert len(doc["fields"]) > 0
        with pymupdf.open(Path("data/synthetic/documents_v2") / doc["filename"]) as pdf:
            page_words: dict[int, list[tuple[float, float]]] = {}
            for page_number, page in enumerate(pdf, start=1):
                width = float(page.rect.width or 595)
                height = float(page.rect.height or 842)
                page_words[page_number] = [
                    (
                        (word[0] + word[2]) * 500 / width,
                        (word[1] + word[3]) * 500 / height,
                    )
                    for word in page.get_text("words")
                ]
        for f in doc["fields"]:
            box = f["bbox"]
            assert 0 <= box["x0"] <= box["x1"] <= 1000
            assert 0 <= box["y0"] <= box["y1"] <= 1000
            assert 0.0 <= f["confidence"] <= 1.0
            assert any(
                box["x0"] <= center_x <= box["x1"]
                and box["y0"] <= center_y <= box["y1"]
                for center_x, center_y in page_words[f["page"]]
            ), f"Field {f['name']} in {doc['doc_id']} does not overlap searchable PDF text"

        # Privacy seeds must be present in every document
        assert len(doc["privacy_seeds"]) >= 4
        types = {seed["type"] for seed in doc["privacy_seeds"]}
        assert "EMAIL_ADDRESS" in types
        assert "IBAN_CODE" in types


def test_document_generator_is_reproducible(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "documents"
    monkeypatch.setattr(generate_documents, "DOCS_DIR", output)
    monkeypatch.setattr(generate_documents, "ANNOTATIONS_FILE", output / "annotations.json")

    generate_documents.generate_documents(num_clean=4, num_adversarial=4, seed=17)
    first_run = {
        path.name: path.read_bytes()
        for path in output.iterdir()
        if path.is_file()
    }

    generate_documents.generate_documents(num_clean=4, num_adversarial=4, seed=17)
    second_run = {
        path.name: path.read_bytes()
        for path in output.iterdir()
        if path.is_file()
    }

    assert first_run == second_run


def test_regulations_corpus_versioning() -> None:
    """Verifies that regulations include superseded and in-force texts with date metadata."""
    reg_path = Path("data/regulations/csddd_regulations.json")
    with open(reg_path, encoding="utf-8") as f:
        regs = json.load(f)

    versions = {r["version_id"]: r for r in regs}
    assert "EU-CSDDD-2024-1760" in versions
    assert "EU-CSDDD-2026-470" in versions

    superseded = versions["EU-CSDDD-2024-1760"]
    assert superseded["status"] == "superseded"
    assert superseded["superseded_by"] == "EU-CSDDD-2026-470"

    current = versions["EU-CSDDD-2026-470"]
    assert current["status"] == "in_force"
    assert current["effective_from"] == "2026-03-18"


def test_golden_set_distribution() -> None:
    """Verifies the 150 golden evaluation cases cover compliant and adversarial scenarios."""
    golden_path = Path("data/golden/golden_set.json")
    with open(golden_path, encoding="utf-8") as f:
        data = json.load(f)

    cases = data["cases"]
    assert len(cases) == 150

    outcomes = {c["expected_verdicts"][0]["expected_outcome"] for c in cases}
    assert "pass" in outcomes
    assert "fail" in outcomes
    assert "escalate" in outcomes
