"""Generate sample compliance certificate PDFs using PyMuPDF (fitz)."""

from pathlib import Path
import fitz

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
SAMPLES_DIR.mkdir(exist_ok=True)

# (filename, issuer, expiry, scope, facility_id, supplier_id)
CERTS = [
    ("valid_cert.pdf",       "Bureau Veritas SA",                        "2028-06-30", "Electronic components manufacturing", "FAC-001", "SUP-001"),
    ("expired_cert.pdf",     "Bureau Veritas SA",                        "2024-01-15", "Electronic components manufacturing", "FAC-001", "SUP-001"),
    ("unknown_issuer.pdf",   "FastCert Ltd",                             "2027-12-31", "Electronic components manufacturing", "FAC-001", "SUP-001"),
    ("scope_mismatch.pdf",   "SGS Societe Generale de Surveillance SA",  "2027-09-30", "Textile dyeing and finishing",        "FAC-001", "SUP-001"),
]

def make_samples() -> None:
    for name, issuer, exp, scope, fac, sup in CERTS:
        doc = fitz.open()
        page = doc.new_page()
        text = f"""CERTIFICATE OF CONFORMITY
Issuer: {issuer}
Supplier ID: {sup}
Facility ID: {fac}
Valid From: 2024-01-01
Valid To: {exp}
Scope: {scope}
"""
        page.insert_text((50, 72), text, fontsize=12)
        out_path = SAMPLES_DIR / name
        doc.save(str(out_path))
        doc.close()
        print(f"Generated {name} at {out_path} ({out_path.stat().st_size} bytes)")

if __name__ == "__main__":
    make_samples()
