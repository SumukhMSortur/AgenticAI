"""Command-line utility to cryptographically verify tenant audit logs."""

import sys
from backend.app.db.session import SessionLocal
from backend.app.db.audit_log import verify_chain


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m backend.app.db.audit_cli <tenant_id_or_org_id>")
        sys.exit(1)

    tenant_id = sys.argv[1]
    with SessionLocal() as db:
        valid, error = verify_chain(db, tenant_id)
        if valid:
            print(f"✓ Cryptographic audit chain verified for tenant {tenant_id}: Integrity 100% OK.")
            sys.exit(0)
        else:
            print(f"✗ AUDIT INTEGRITY FAILURE for tenant {tenant_id}: {error}")
            sys.exit(2)


if __name__ == "__main__":
    main()
