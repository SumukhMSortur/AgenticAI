"""
Generate minimal but realistic compliance certificate PDFs using only Python builtins.
Uses manual PDF construction (no third-party libraries required).
"""
import os
import zlib

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

def escape_pdf_string(s):
    return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

def build_pdf(lines_of_text):
    """
    Build a minimal valid PDF with the given list of text lines.
    Returns bytes of the PDF.
    """
    # Font and page setup
    page_width = 595   # A4 points
    page_height = 842

    # Build content stream
    content_parts = []
    content_parts.append("BT")
    content_parts.append("/F1 14 Tf")  # title font size

    y = 750
    for i, line in enumerate(lines_of_text):
        safe = escape_pdf_string(line)
        if i == 0:
            content_parts.append(f"/F1 16 Tf")
            content_parts.append(f"50 {y} Td")
            content_parts.append(f"({safe}) Tj")
            content_parts.append(f"/F1 12 Tf")
            y -= 30
        elif line == "":
            y -= 15
        elif line.startswith("---"):
            # Draw a horizontal rule as text separator
            content_parts.append(f"0 {y} Td")
            content_parts.append(f"(----------------------------------------------------------------) Tj")
            y -= 20
        else:
            content_parts.append(f"0 {y} Td")
            content_parts.append(f"({safe}) Tj")
            # Reset position using absolute positioning each line
            y -= 20

    content_parts.append("ET")
    content_stream = "\n".join(content_parts).encode("latin-1")

    # PDF object builder
    objects = []  # list of (obj_num, bytes)
    offsets = []

    def add_obj(content_bytes):
        obj_num = len(objects) + 1
        objects.append(content_bytes)
        return obj_num

    # Object 1: Catalog
    catalog_num = add_obj(None)  # placeholder
    # Object 2: Pages
    pages_num = add_obj(None)
    # Object 3: Page
    page_num = add_obj(None)
    # Object 4: Font
    font_num = add_obj(None)
    # Object 5: Content stream
    content_num = add_obj(None)

    # Build actual object bytes
    obj_bytes = {}

    # Content stream object
    obj_bytes[content_num] = (
        f"<< /Length {len(content_stream)} >>\n"
        f"stream\n"
    ).encode() + content_stream + b"\nendstream"

    # Font object
    obj_bytes[font_num] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )

    # Page object
    obj_bytes[page_num] = (
        f"<< /Type /Page /Parent {pages_num} 0 R "
        f"/MediaBox [0 0 {page_width} {page_height}] "
        f"/Contents {content_num} 0 R "
        f"/Resources << /Font << /F1 {font_num} 0 R >> >> >>"
    ).encode()

    # Pages object
    obj_bytes[pages_num] = (
        f"<< /Type /Pages /Kids [{page_num} 0 R] /Count 1 >>"
    ).encode()

    # Catalog object
    obj_bytes[catalog_num] = (
        f"<< /Type /Catalog /Pages {pages_num} 0 R >>"
    ).encode()

    # Assemble PDF
    pdf = b"%PDF-1.4\n"
    pdf += b"%\xe2\xe3\xcf\xd3\n"  # binary comment to mark as binary file

    obj_offset = {}
    for i in range(1, len(objects) + 1):
        obj_offset[i] = len(pdf)
        pdf += f"{i} 0 obj\n".encode()
        pdf += obj_bytes[i]
        pdf += b"\nendobj\n"

    # Cross-reference table
    xref_offset = len(pdf)
    num_objs = len(objects)
    pdf += f"xref\n0 {num_objs + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for i in range(1, num_objs + 1):
        pdf += f"{obj_offset[i]:010d} 00000 n \n".encode()

    pdf += (
        f"trailer\n"
        f"<< /Size {num_objs + 1} /Root {catalog_num} 0 R >>\n"
        f"startxref\n"
        f"{xref_offset}\n"
        f"%%EOF\n"
    ).encode()

    return pdf


CERTS = [
    {
        "filename": "valid_cert.pdf",
        "lines": [
            "CERTIFICATE OF CONFORMITY",
            "---",
            "",
            "Standard:          ISO 14001:2015 Environmental Management Systems",
            "Certificate No:    CERT-BV-2024-001",
            "Issuer:            Bureau Veritas Certification",
            "Issue Date:        2024-07-01",
            "Expiry Date:       2028-06-30",
            "",
            "---",
            "CERTIFICATE HOLDER",
            "",
            "Organisation:      Apex Electronics Pte Ltd",
            "Address:           12 Tech Park Avenue, Singapore 638000",
            "",
            "---",
            "SCOPE OF CERTIFICATION",
            "",
            "Electronic components manufacturing, PCB assembly",
            "",
            "---",
            "This certificate confirms that the above organisation has",
            "implemented an Environmental Management System that meets",
            "the requirements of ISO 14001:2015.",
            "",
            "Signed: __________________________",
            "Dr. Marie Dupont, Lead Auditor",
            "Bureau Veritas Certification",
            "",
            "Accreditation Body: UKAS (United Kingdom Accreditation Service)",
            "Accreditation No:   UKAS-EMS-12345",
        ],
    },
    {
        "filename": "expired_cert.pdf",
        "lines": [
            "CERTIFICATE OF CONFORMITY",
            "---",
            "",
            "Standard:          ISO 14001:2015 Environmental Management Systems",
            "Certificate No:    CERT-BV-2022-099",
            "Issuer:            Bureau Veritas Certification",
            "Issue Date:        2022-01-15",
            "Expiry Date:       2024-01-15",
            "",
            "---",
            "CERTIFICATE HOLDER",
            "",
            "Organisation:      ShineTech Manufacturing Ltd",
            "Address:           88 Industrial Road, Shenzhen 518000, China",
            "",
            "---",
            "SCOPE OF CERTIFICATION",
            "",
            "Electronic components manufacturing",
            "",
            "---",
            "This certificate confirms that the above organisation has",
            "implemented an Environmental Management System that meets",
            "the requirements of ISO 14001:2015.",
            "",
            "Signed: __________________________",
            "Mr. James Holloway, Lead Auditor",
            "Bureau Veritas Certification",
            "",
            "Accreditation Body: COFRAC (France)",
            "Accreditation No:   COFRAC-EMS-7891",
        ],
    },
    {
        "filename": "unknown_issuer.pdf",
        "lines": [
            "CERTIFICATE OF CONFORMITY",
            "---",
            "",
            "Standard:          ISO 14001:2015 Environmental Management Systems",
            "Certificate No:    CERT-FC-2024-042",
            "Issuer:            FastCert Ltd",
            "Issue Date:        2024-03-20",
            "Expiry Date:       2027-12-31",
            "",
            "---",
            "CERTIFICATE HOLDER",
            "",
            "Organisation:      Bright Components Co.",
            "Address:           Unit 5, Commerce Park, Dublin, Ireland",
            "",
            "---",
            "SCOPE OF CERTIFICATION",
            "",
            "Electronic components manufacturing",
            "",
            "---",
            "This certificate confirms that the above organisation has",
            "implemented an Environmental Management System that meets",
            "the requirements of ISO 14001:2015.",
            "",
            "Signed: __________________________",
            "Ms. Sarah O'Brien, Lead Auditor",
            "FastCert Ltd",
            "",
            "Accreditation Body: FastCert Internal Accreditation Board",
            "Accreditation No:   FC-ACC-2024-001",
        ],
    },
    {
        "filename": "scope_mismatch.pdf",
        "lines": [
            "CERTIFICATE OF CONFORMITY",
            "---",
            "",
            "Standard:          ISO 14001:2015 Environmental Management Systems",
            "Certificate No:    CERT-SGS-2024-017",
            "Issuer:            SGS SA",
            "Issue Date:        2024-09-30",
            "Expiry Date:       2027-09-30",
            "",
            "---",
            "CERTIFICATE HOLDER",
            "",
            "Organisation:      TexDye Industries Ltd",
            "Address:           Plot 22, Industrial Zone, Dhaka 1216, Bangladesh",
            "",
            "---",
            "SCOPE OF CERTIFICATION",
            "",
            "Textile dyeing and finishing",
            "",
            "---",
            "This certificate confirms that the above organisation has",
            "implemented an Environmental Management System that meets",
            "the requirements of ISO 14001:2015.",
            "",
            "Signed: __________________________",
            "Mr. Henrik Larsson, Lead Auditor",
            "SGS SA",
            "",
            "Accreditation Body: DAkkS (Germany)",
            "Accreditation No:   DAkkS-EMS-55678",
        ],
    },
]

def main():
    for cert in CERTS:
        pdf_bytes = build_pdf(cert["lines"])
        out_path = os.path.join(OUTPUT_DIR, cert["filename"])
        with open(out_path, "wb") as f:
            f.write(pdf_bytes)
        size = os.path.getsize(out_path)
        header = open(out_path, "rb").read(4)
        status = "OK" if header == b"%PDF" and size > 500 else "FAIL"
        print(f"{cert['filename']}: {size} bytes, header={header}, status={status}")

if __name__ == "__main__":
    main()
