"""Generates synthetic supplier compliance PDFs with ground-truth bounding boxes and privacy seeds."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pymupdf

DOCS_DIR = Path("data/synthetic/documents_v2")
ANNOTATIONS_FILE = DOCS_DIR / "annotations.json"
DOCUMENT_TYPES = {
    "certificate": "CERTIFICATE OF COMPLIANCE",
    "bill_of_materials": "BILL OF MATERIALS - CERTIFIED SCOPE",
    "invoice": "SUPPLIER INVOICE - COMPLIANCE MATERIALS",
    "chemical_test_report": "CHEMICAL TEST REPORT",
}

PRIVACY_NAMES = [
    "Heinrich Müller",
    "Claire Dubois",
    "Mateo Rossi",
    "Fatima Al-Mansoor",
    "Linh Nguyen",
    "Rajesh Sharma",
]
PRIVACY_EMAILS = [
    "h.mueller@cert-auth.de",
    "c.dubois@ecocert-audit.eu",
    "m.rossi@textile-verify.it",
    "contact@audit-partner.org",
]
PRIVACY_IBANS = [
    "DE89370400440532013000",
    "FR7630006000011234567890189",
    "NL91ABNA0417164300",
    "IT60X0542811101000000123456",
]
PRIVACY_PHONES = ["+49 89 2018 4021", "+33 1 42 68 55 00", "+39 02 8739 1120", "+44 20 7946 0912"]


def get_doc_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def normalized_bbox(page: pymupdf.Page, text: str, fallback: dict[str, int]) -> dict[str, int]:
    """Return a value's measured page box in LayoutLM's normalized coordinate space."""
    rects = page.search_for(text)
    if not rects:
        return fallback
    rect = rects[0]
    width = float(page.rect.width or 595)
    height = float(page.rect.height or 842)
    return {
        "x0": int(np.clip(round(rect.x0 * 1000 / width), 0, 1000)),
        "y0": int(np.clip(round(rect.y0 * 1000 / height), 0, 1000)),
        "x1": int(np.clip(round(rect.x1 * 1000 / width), 0, 1000)),
        "y1": int(np.clip(round(rect.y1 * 1000 / height), 0, 1000)),
    }


def render_pdf_page(
    page: pymupdf.Page,
    lines: list[tuple[str, float, float, int, tuple[float, float, float]]],
    draw_stamp: bool = True,
    draw_signature: bool = True,
    skew_degrees: float = 0.0,
    scan_noise: int = 0,
    rng: np.random.Generator | None = None,
) -> None:
    """Renders structured text lines and visual mock artifacts onto a PyMuPDF page."""
    for text, x, y, size, color in lines:
        origin = pymupdf.Point(x, y)
        morph = (
            (origin, pymupdf.Matrix(1, 0, 0, 1, 0, 0).prerotate(skew_degrees))
            if skew_degrees
            else None
        )
        page.insert_text(
            origin,
            text,
            fontsize=size,
            color=color,
            fontname="helv",
            morph=morph,
        )

    if draw_stamp:
        # Mock approval stamp: red bordered rectangle with rotated/bold text
        rect = pymupdf.Rect(400, 680, 550, 760)
        page.draw_rect(rect, color=(0.8, 0.1, 0.1), width=2.0)
        page.insert_text(
            pymupdf.Point(415, 715), "OFFICIALLY VERIFIED", fontsize=11, color=(0.8, 0.1, 0.1)
        )
        page.insert_text(
            pymupdf.Point(430, 735), "ISO/IEC 17065", fontsize=9, color=(0.8, 0.1, 0.1)
        )

    if draw_signature:
        # Mock signature stroke line
        page.draw_line(
            pymupdf.Point(100, 740), pymupdf.Point(260, 740), color=(0.1, 0.1, 0.3), width=1.5
        )
        page.insert_text(
            pymupdf.Point(100, 755),
            "Authorized Compliance Officer Signature",
            fontsize=8,
            color=(0.3, 0.3, 0.3),
        )

    if rng is not None:
        for _ in range(scan_noise):
            point = pymupdf.Point(
                float(rng.uniform(0, page.rect.width)),
                float(rng.uniform(0, page.rect.height)),
            )
            shade = float(rng.uniform(0.65, 0.9))
            page.draw_circle(
                point,
                float(rng.uniform(0.2, 0.7)),
                color=(shade, shade, shade),
                fill=(shade, shade, shade),
                overlay=False,
            )


def add_continuation_page(doc: pymupdf.Document, doc_id: str, supplier_id: str) -> None:
    """Add a second, searchable page to exercise multi-page document handling."""
    page = doc.new_page(width=595, height=842)
    page.insert_text(pymupdf.Point(50, 80), "SUPPLIER COMPLIANCE EVIDENCE - CONTINUED", fontsize=14)
    page.insert_text(pymupdf.Point(50, 130), f"Document reference: {doc_id}", fontsize=10)
    page.insert_text(pymupdf.Point(50, 160), f"Supplier ID: {supplier_id}", fontsize=10)
    page.insert_text(pymupdf.Point(50, 190), "Supporting evidence and audit notes continue on this page.", fontsize=10)


def document_type_lines(
    document_type: str,
    doc_id: str,
    material: str,
    unit_price: str,
) -> list[tuple[str, float, float, int, tuple[float, float, float]]]:
    """Add document-specific content while retaining shared compliance fields."""
    black = (0.15, 0.15, 0.15)
    if document_type == "bill_of_materials":
        return [
            (f"BOM Reference: BOM-{doc_id}", 50, 545, 9, black),
            (f"Component 1: {material}", 50, 565, 9, black),
            ("Composition verified against supplier declaration", 50, 585, 9, black),
        ]
    if document_type == "invoice":
        return [
            (f"Invoice Number: INV-{doc_id}", 50, 545, 9, black),
            ("Invoice Date: 2026-02-15", 50, 565, 9, black),
            (f"Invoice Total: {unit_price}", 50, 585, 9, black),
        ]
    if document_type == "chemical_test_report":
        return [
            (f"Test Report Number: CHEM-{doc_id}", 50, 545, 9, black),
            ("Test Method: ISO 17075", 50, 565, 9, black),
            ("Chemical: restricted azo dyes", 50, 585, 9, black),
            ("Result: compliant", 50, 605, 9, black),
        ]
    return []


def generate_documents(
    num_clean: int = 320,
    num_adversarial: int = 160,
    seed: int = 42,
) -> Path:
    """Generates synthetic PDFs with ground-truth field annotations and privacy seeds."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    _rng = np.random.default_rng(seed)

    all_annotations: list[dict] = []

    # 1. Clean GOTS Certificates
    issuers = [
        ("Control Union Certifications B.V.", "ISS-001"),
        ("Ecocert Greenlife S.A.S.", "ISS-002"),
        ("OEKO-TEX Association (Service GmbH)", "ISS-003"),
        ("Intertek Group plc", "ISS-005"),
    ]

    materials = [
        "100% Organic Cotton",
        "80% Organic Cotton, 20% Recycled Polyester",
        "100% GOTS Certified Cotton Jersey",
        "95% Organic Cotton, 5% Elastane",
    ]

    for i in range(num_clean):
        doc_id = f"DOC-CLN-{i + 1:04d}"
        pdf_path = DOCS_DIR / f"{doc_id}.pdf"

        document_type = tuple(DOCUMENT_TYPES)[i % len(DOCUMENT_TYPES)]
        has_continuation = i % 7 == 0
        issuer_name, _ = issuers[i % len(issuers)]
        material = materials[i % len(materials)]
        valid_from = "2024-01-15"
        valid_to = f"202{7 + (i % 3)}-12-31"  # valid well into 2027-2029
        facility_id = f"FAC-BAN-{100 + (i % 40):03d}"
        supplier_id = f"SUP-{200 + (i % 30):03d}"

        # Privacy seeds
        contact_name = PRIVACY_NAMES[i % len(PRIVACY_NAMES)]
        contact_email = PRIVACY_EMAILS[i % len(PRIVACY_EMAILS)]
        bank_iban = PRIVACY_IBANS[i % len(PRIVACY_IBANS)]
        unit_price = f"EUR {14.50 + (i % 10) * 1.25:.2f} / kg"

        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)  # Standard A4: 595 x 842 pt
        continuation_page = None

        # Lines to insert: (text, x, y, size, rgb_color)
        lines = [
            (DOCUMENT_TYPES[document_type], 100, 80, 16, (0.05, 0.25, 0.45)),
            ("Certification Scheme: GOTS", 50, 105, 10, (0.1, 0.1, 0.1)),
            (f"Certificate No: GOTS-{doc_id}", 50, 130, 10, (0.2, 0.2, 0.2)),
            (f"Certification Body: {issuer_name}", 50, 160, 11, (0.1, 0.1, 0.1)),
            (f"Applicant Facility ID: {facility_id}", 50, 190, 10, (0.1, 0.1, 0.1)),
            (f"Supplier ID: {supplier_id}", 50, 215, 10, (0.1, 0.1, 0.1)),
            (f"Valid From: {valid_from}", 50, 245, 10, (0.1, 0.1, 0.1)),
            (f"Valid To: {valid_to}", 50, 270, 10, (0.1, 0.1, 0.1)),
            ("Certified Product Category / Material Scope:", 50, 310, 11, (0.05, 0.25, 0.45)),
            (f"  • {material}", 60, 335, 10, (0.1, 0.1, 0.1)),
            (
                "Standards: Global Organic Textile Standard (GOTS) Version 7.0",
                50,
                375,
                10,
                (0.1, 0.1, 0.1),
            ),
            ("Commercial & Audit Contact (Confidential):", 50, 420, 10, (0.4, 0.4, 0.4)),
            (f"  Auditor Name: {contact_name}", 60, 440, 9, (0.3, 0.3, 0.3)),
            (f"  Direct Email: {contact_email}", 60, 460, 9, (0.3, 0.3, 0.3)),
            (f"  Fee Settlement IBAN: {bank_iban}", 60, 480, 9, (0.3, 0.3, 0.3)),
            (f"  Certified Material Unit Price: {unit_price}", 60, 500, 9, (0.3, 0.3, 0.3)),
            (f"Page 1 of {2 if has_continuation else 1}", 260, 800, 9, (0.5, 0.5, 0.5)),
        ]
        lines.extend(document_type_lines(document_type, doc_id, material, unit_price))

        render_pdf_page(
            page,
            lines,
            draw_stamp=i % 2 == 0,
            draw_signature=i % 3 != 0,
            skew_degrees=(-1.5, 0.0, 1.5)[i % 3],
            scan_noise=80 if i % 2 else 0,
            rng=_rng,
        )
        if has_continuation:
            add_continuation_page(doc, doc_id, supplier_id)
            page = doc[0]
            continuation_page = doc[1]
        pdf_bytes = doc.tobytes(no_new_id=True, reproducible=True)

        def norm_box(x: float, y: float, w: float, h: float) -> dict:
            return {
                "x0": int(np.clip(x * 1000 / 595, 0, 1000)),
                "y0": int(np.clip((y - h) * 1000 / 842, 0, 1000)),
                "x1": int(np.clip((x + w) * 1000 / 595, 0, 1000)),
                "y1": int(np.clip(y * 1000 / 842, 0, 1000)),
            }

        fields = [
            {
                "name": "certificate_type",
                "value": "GOTS",
                "page": 1,
                "bbox": normalized_bbox(page, "GOTS", norm_box(160, 80, 260, 20)),
                "confidence": 1.0,
            },
            {
                "name": "issuer",
                "value": issuer_name,
                "page": 1,
                "bbox": normalized_bbox(page, issuer_name, norm_box(50, 160, 300, 15)),
                "confidence": 1.0,
            },
            {
                "name": "facility_id",
                "value": facility_id,
                "page": 1,
                "bbox": normalized_bbox(page, facility_id, norm_box(50, 190, 200, 15)),
                "confidence": 1.0,
            },
            {
                "name": "supplier_id",
                "value": supplier_id,
                "page": 1,
                "bbox": normalized_bbox(page, supplier_id, norm_box(50, 215, 180, 15)),
                "confidence": 1.0,
            },
            {
                "name": "valid_from",
                "value": valid_from,
                "page": 1,
                "bbox": normalized_bbox(page, valid_from, norm_box(50, 245, 150, 15)),
                "confidence": 1.0,
            },
            {
                "name": "valid_to",
                "value": valid_to,
                "page": 1,
                "bbox": normalized_bbox(page, valid_to, norm_box(50, 270, 150, 15)),
                "confidence": 1.0,
            },
            {
                "name": "scope_materials",
                "value": material,
                "page": 1,
                "bbox": normalized_bbox(page, material, norm_box(60, 335, 300, 15)),
                "confidence": 1.0,
            },
        ]
        if continuation_page is not None:
            fields.append(
                {
                    "name": "supplier_id",
                    "value": supplier_id,
                    "page": 2,
                    "bbox": normalized_bbox(
                        continuation_page,
                        supplier_id,
                        {"x0": 80, "y0": 170, "x1": 420, "y1": 190},
                    ),
                    "confidence": 1.0,
                }
            )
        pdf_path.write_bytes(pdf_bytes)
        doc.close()
        doc_hash = get_doc_hash(pdf_bytes)

        privacy_seeds = [
            {"type": "PERSON", "value": contact_name, "page": 1},
            {"type": "EMAIL_ADDRESS", "value": contact_email, "page": 1},
            {"type": "IBAN_CODE", "value": bank_iban, "page": 1},
            {"type": "PRICE", "value": unit_price, "page": 1},
        ]

        all_annotations.append(
            {
                "doc_id": doc_id,
                "filename": f"{doc_id}.pdf",
                "doc_hash": doc_hash,
                "doc_type": document_type,
                "category": "clean",
                "page_count": 2 if has_continuation else 1,
                "visual_variants": {
                    "skew_degrees": (-1.5, 0.0, 1.5)[i % 3],
                    "scan_noise": i % 2 == 1,
                    "stamp": i % 2 == 0,
                    "signature": i % 3 != 0,
                    "multi_page": has_continuation,
                },
                "fields": fields,
                "privacy_seeds": privacy_seeds,
                "expected_outcome": "pass",
            }
        )

    # 2. Adversarial Variants
    adversarial_configs = [
        (
            "ADV-EXP",
            "expired_certificate",
            "2024-01-01",
            "2024-12-31",
            "Control Union Certifications B.V.",
            "100% Organic Cotton",
            "V-EXP-001",
            "fail",
        ),
        (
            "ADV-EXP-WARN",
            "near_expiry_certificate",
            "2024-01-01",
            "2026-11-20",
            "Control Union Certifications B.V.",
            "100% Organic Cotton",
            "V-EXP-002",
            "escalate",
        ),
        (
            "ADV-ISS-UNAPPROVED",
            "unapproved_issuer",
            "2024-01-01",
            "2028-12-31",
            "Fake Green Audit Global Ltd",
            "100% Organic Cotton",
            "V-ISS-001",
            "fail",
        ),
        (
            "ADV-ISS-FUZZY",
            "fuzzy_issuer_name",
            "2024-01-01",
            "2028-12-31",
            "Control Union Certification B.V.",
            "100% Organic Cotton",
            "V-ISS-002",
            "escalate",
        ),
        (
            "ADV-SCOPE-MISMATCH",
            "scope_mismatch",
            "2024-01-01",
            "2028-12-31",
            "OEKO-TEX Association (Service GmbH)",
            "100% Recycled Polyester",
            "V-SCOPE-001",
            "fail",
        ),
        (
            "ADV-FAC-MISMATCH",
            "facility_mismatch",
            "2024-01-01",
            "2028-12-31",
            "Ecocert Greenlife S.A.S.",
            "100% Organic Cotton",
            "V-SCOPE-002",
            "fail",
        ),
        (
            "ADV-MISSING-PAGE",
            "missing_page",
            "2024-01-01",
            "2028-12-31",
            "Control Union Certifications B.V.",
            "100% Organic Cotton",
            "DATA-MISSING-PAGE",
            "escalate",
        ),
        (
            "ADV-SUPPLIER-CONFLICT",
            "conflicting_supplier_ids",
            "2024-01-01",
            "2028-12-31",
            "Ecocert Greenlife S.A.S.",
            "100% Organic Cotton",
            "DATA-SUPPLIER-CONFLICT",
            "escalate",
        ),
        (
            "ADV-ISS-FORGED",
            "forged_looking_issuer",
            "2024-01-01",
            "2028-12-31",
            "Control Union Certifications B.V. - AUTHENTICATED",
            "100% Organic Cotton",
            "V-ISS-001",
            "fail",
        ),
    ]

    for j in range(num_adversarial):
        code, kind, v_from, v_to, issuer, mat, rule, outcome = adversarial_configs[
            j % len(adversarial_configs)
        ]
        doc_id = f"DOC-{code}-{j + 1:03d}"
        pdf_path = DOCS_DIR / f"{doc_id}.pdf"
        document_type = tuple(DOCUMENT_TYPES)[(num_clean + j) % len(DOCUMENT_TYPES)]
        is_missing_page = kind == "missing_page"
        has_continuation = j % 7 == 0 and not is_missing_page

        facility_id = f"FAC-ADV-{j + 1:03d}"
        supplier_id = f"SUP-ADV-{j + 1:03d}"
        conflicting_supplier_id = f"SUP-CONFLICT-{j + 1:03d}"
        contact_name = PRIVACY_NAMES[(j + 2) % len(PRIVACY_NAMES)]
        contact_email = PRIVACY_EMAILS[(j + 2) % len(PRIVACY_EMAILS)]
        bank_iban = PRIVACY_IBANS[(j + 2) % len(PRIVACY_IBANS)]
        unit_price = f"EUR {22.00 + j * 0.50:.2f} / meter"

        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        continuation_page = None

        lines = [
            (DOCUMENT_TYPES[document_type], 100, 80, 16, (0.5, 0.1, 0.1)),
            (f"Certificate No: ADV-{doc_id}", 50, 130, 10, (0.2, 0.2, 0.2)),
            ("Certificate Type: Standard Certificate", 50, 145, 10, (0.2, 0.2, 0.2)),
            (f"Certification Body: {issuer}", 50, 160, 11, (0.1, 0.1, 0.1)),
            (f"Applicant Facility ID: {facility_id}", 50, 190, 10, (0.1, 0.1, 0.1)),
            (f"Supplier ID: {supplier_id}", 50, 215, 10, (0.1, 0.1, 0.1)),
            (f"Valid From: {v_from}", 50, 245, 10, (0.1, 0.1, 0.1)),
            (f"Valid To: {v_to}", 50, 270, 10, (0.1, 0.1, 0.1)),
            (f"Certified Material Scope: {mat}", 50, 310, 11, (0.1, 0.1, 0.1)),
            ("Billing & Audit Contact (Commercial):", 50, 360, 10, (0.4, 0.4, 0.4)),
            (f"  Contact Name: {contact_name}", 60, 385, 9, (0.3, 0.3, 0.3)),
            (f"  Contact Email: {contact_email}", 60, 405, 9, (0.3, 0.3, 0.3)),
            (f"  Bank IBAN: {bank_iban}", 60, 425, 9, (0.3, 0.3, 0.3)),
            (f"  Unit Contract Price: {unit_price}", 60, 445, 9, (0.3, 0.3, 0.3)),
            (
                f"Supplier ID: {conflicting_supplier_id}",
                60,
                485,
                9,
                (0.3, 0.3, 0.3),
            )
            if kind == "conflicting_supplier_ids"
            else ("", 60, 485, 9, (0.3, 0.3, 0.3)),
            (f"Page 1 of {2 if has_continuation or is_missing_page else 1}", 260, 800, 9, (0.5, 0.5, 0.5)),
        ]

        lines = [line for line in lines if line[0]]
        lines.extend(document_type_lines(document_type, doc_id, mat, unit_price))
        render_pdf_page(
            page,
            lines,
            draw_stamp=j % 2 == 0,
            draw_signature=j % 3 != 0,
            skew_degrees=(-1.5, 0.0, 1.5)[j % 3],
            scan_noise=80 if j % 2 else 0,
            rng=_rng,
        )
        if has_continuation:
            add_continuation_page(doc, doc_id, supplier_id)
            page = doc[0]
            continuation_page = doc[1]
        pdf_bytes = doc.tobytes(no_new_id=True, reproducible=True)
        actual_page_count = len(doc)

        fields = [
            {
                "name": "certificate_type",
                "value": "Standard Certificate",
                "page": 1,
                "bbox": normalized_bbox(
                    page,
                    "Standard Certificate",
                    {"x0": 235, "y0": 71, "x1": 672, "y1": 95},
                ),
                "confidence": 0.99,
            },
            {
                "name": "issuer",
                "value": issuer,
                "page": 1,
                "bbox": normalized_bbox(
                    page, issuer, {"x0": 84, "y0": 172, "x1": 588, "y1": 190}
                ),
                "confidence": 0.98,
            },
            {
                "name": "facility_id",
                "value": facility_id,
                "page": 1,
                "bbox": normalized_bbox(
                    page, facility_id, {"x0": 84, "y0": 207, "x1": 420, "y1": 225}
                ),
                "confidence": 0.97,
            },
            {
                "name": "supplier_id",
                "value": supplier_id,
                "page": 1,
                "bbox": normalized_bbox(
                    page, supplier_id, {"x0": 84, "y0": 237, "x1": 386, "y1": 255}
                ),
                "confidence": 0.98,
            },
            {
                "name": "valid_from",
                "value": v_from,
                "page": 1,
                "bbox": normalized_bbox(
                    page, v_from, {"x0": 84, "y0": 273, "x1": 336, "y1": 290}
                ),
                "confidence": 0.98,
            },
            {
                "name": "valid_to",
                "value": v_to,
                "page": 1,
                "bbox": normalized_bbox(
                    page, v_to, {"x0": 84, "y0": 302, "x1": 336, "y1": 320}
                ),
                "confidence": 0.99,
            },
            {
                "name": "scope_materials",
                "value": mat,
                "page": 1,
                "bbox": normalized_bbox(
                    page, mat, {"x0": 84, "y0": 350, "x1": 588, "y1": 368}
                ),
                "confidence": 0.98,
            },
        ]
        if kind == "conflicting_supplier_ids":
            fields.append(
                {
                    "name": "supplier_id",
                    "value": conflicting_supplier_id,
                    "page": 1,
                    "bbox": normalized_bbox(
                        page,
                        conflicting_supplier_id,
                        {"x0": 100, "y0": 560, "x1": 500, "y1": 590},
                    ),
                    "confidence": 1.0,
                }
            )
        if continuation_page is not None:
            fields.append(
                {
                    "name": "supplier_id",
                    "value": supplier_id,
                    "page": 2,
                    "bbox": normalized_bbox(
                        continuation_page,
                        supplier_id,
                        {"x0": 80, "y0": 170, "x1": 420, "y1": 190},
                    ),
                    "confidence": 1.0,
                }
            )
        pdf_path.write_bytes(pdf_bytes)
        doc.close()
        doc_hash = get_doc_hash(pdf_bytes)

        privacy_seeds = [
            {"type": "PERSON", "value": contact_name, "page": 1},
            {"type": "EMAIL_ADDRESS", "value": contact_email, "page": 1},
            {"type": "IBAN_CODE", "value": bank_iban, "page": 1},
            {"type": "PRICE", "value": unit_price, "page": 1},
        ]

        all_annotations.append(
            {
                "doc_id": doc_id,
                "filename": f"{doc_id}.pdf",
                "doc_hash": doc_hash,
                "doc_type": document_type,
                "category": "adversarial",
                "adversarial_kind": kind,
                "page_count": actual_page_count,
                "expected_page_count": 2 if is_missing_page else actual_page_count,
                "missing_pages": [2] if is_missing_page else [],
                "visual_variants": {
                    "skew_degrees": (-1.5, 0.0, 1.5)[j % 3],
                    "scan_noise": j % 2 == 1,
                    "stamp": j % 2 == 0,
                    "signature": j % 3 != 0,
                    "multi_page": has_continuation,
                },
                "fields": fields,
                "privacy_seeds": privacy_seeds,
                "expected_outcome": outcome,
                "expected_rule": rule,
            }
        )

    with open(ANNOTATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_annotations, f, indent=2)

    print(
        f"Generated {len(all_annotations)} synthetic PDFs (clean={num_clean}, adv={num_adversarial}) at {DOCS_DIR}"
    )
    return ANNOTATIONS_FILE


if __name__ == "__main__":
    generate_documents()
