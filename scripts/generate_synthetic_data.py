"""Master data generation and manifest verification script for EcoChain Copilot."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.generate_audit_histories import generate_audit_histories
from scripts.generate_documents import generate_documents
from scripts.generate_golden_set import generate_golden_set
from scripts.generate_issuer_registry import generate_issuer_registry
from scripts.generate_regulations import generate_regulations

DATA_DIR = Path("data")
MANIFEST_FILE = DATA_DIR / "MANIFEST.json"
MASTER_SEED = 42


def compute_file_sha256(path: Path) -> str:
    """Computes SHA-256 hex digest for a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_all_data(seed: int = MASTER_SEED) -> dict[str, str]:
    """Runs all data generators sequentially and creates data/MANIFEST.json."""
    print("\n==========================================")
    print(f"Executing EcoChain Data Generators (Seed={seed})")
    print("==========================================")

    # 1. Mock Approved Issuers Registry
    generate_issuer_registry()

    # 2. Versioned Regulations
    generate_regulations()

    # 3. Multi-year Factory Audit Histories (450 factories, 36 months)
    generate_audit_histories(num_factories=450, seed=seed)

    # 4. Supplier Documents & Annotations with Privacy Seeds
    generate_documents(num_clean=120, num_adversarial=60, seed=seed)

    # 5. Golden Evaluation Benchmark Set (150 cases)
    generate_golden_set(num_cases=150, seed=seed)

    # 6. Build Manifest of all generated data files
    print("\nComputing SHA-256 hashes for data/MANIFEST.json...")
    manifest_entries: dict[str, str] = {}

    target_files = [
        Path("data/registry/approved_issuers.csv"),
        Path("data/regulations/csddd_regulations.json"),
        Path("data/synthetic/audit_histories_train.json"),
        Path("data/synthetic/audit_histories_val.json"),
        Path("data/synthetic/audit_histories_test.json"),
        Path("data/synthetic/documents/annotations.json"),
        Path("data/golden/golden_set.json"),
    ]

    for p in target_files:
        if p.exists():
            rel_path = p.as_posix()
            manifest_entries[rel_path] = compute_file_sha256(p)

    manifest_data = {
        "generator_version": "1.0.0",
        "master_seed": seed,
        "total_files_tracked": len(manifest_entries),
        "files": manifest_entries,
    }

    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    print(
        f"Manifest written successfully with {len(manifest_entries)} tracked files at {MANIFEST_FILE}"
    )
    return manifest_entries


def verify_manifest() -> bool:
    """Verifies that currently existing files on disk match the committed manifest exactly."""
    if not MANIFEST_FILE.exists():
        print(f"Error: {MANIFEST_FILE} not found. Run generation first.")
        return False

    with open(MANIFEST_FILE, encoding="utf-8") as f:
        manifest = json.load(f)

    files = manifest.get("files", {})
    all_matched = True

    print("\nVerifying data/MANIFEST.json byte-identical integrity...")
    for rel_path, expected_hash in files.items():
        p = Path(rel_path)
        if not p.exists():
            print(f"MISSING: {rel_path}")
            all_matched = False
            continue

        actual_hash = compute_file_sha256(p)
        if actual_hash != expected_hash:
            print(
                f"MISMATCH: {rel_path} (expected {expected_hash[:12]}..., got {actual_hash[:12]}...)"
            )
            all_matched = False
        else:
            print(f"MATCH: {rel_path} ({actual_hash[:12]}...)")

    if all_matched:
        print("\nAll data files strictly match MANIFEST.json! (Reproducibility: 100%)")
    else:
        print("\nIntegrity verification FAILED: discrepancies found.")

    return all_matched


def main() -> None:
    parser = argparse.ArgumentParser(description="EcoChain Data Generation and Verification")
    parser.add_argument(
        "--verify", action="store_true", help="Verify existing data against manifest"
    )
    parser.add_argument("--seed", type=int, default=MASTER_SEED, help="Master RNG seed")
    args = parser.parse_args()

    if args.verify:
        success = verify_manifest()
        sys.exit(0 if success else 1)
    else:
        generate_all_data(seed=args.seed)
        success = verify_manifest()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
