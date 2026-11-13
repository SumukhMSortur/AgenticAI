"""Python cross-platform smoke test for EcoChain Copilot."""

import os
import sys
import time
from pathlib import Path
import urllib.request
import urllib.parse
import json

API_URL = os.environ.get("ECOCHAIN_API_URL", "http://127.0.0.1:8000")
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


def check_ready() -> None:
    print(f"--> Checking API readiness at {API_URL}/readyz...")
    try:
        with urllib.request.urlopen(f"{API_URL}/readyz", timeout=5) as res:
            if res.status == 200:
                print("✓ API is ready.")
                return
    except Exception as e:
        print(f"ERROR: API ready check failed: {e}")
        sys.exit(1)


def submit_and_poll(sample_filename: str, expected_status: str) -> None:
    file_path = SAMPLES_DIR / sample_filename
    if not file_path.exists():
        print(f"ERROR: Sample file {file_path} not found.")
        sys.exit(1)

    print(f"--> Submitting {sample_filename} (expected: {expected_status})...")
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="assessment_date"\r\n\r\n'
        f'{time.strftime("%Y-%m-%d")}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="query"\r\n\r\nAssess {sample_filename}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{sample_filename}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode("latin-1") + file_bytes + f"\r\n--{boundary}--\r\n".encode("latin-1")

    req = urllib.request.Request(
        f"{API_URL}/v1/jobs",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode())
            job_id = data["id"]
            print(f"    Job created with ID: {job_id}")
    except Exception as e:
        print(f"ERROR: Job submission failed: {e}")
        sys.exit(1)

    # Poll status
    current_status = "queued"
    overall_status = None
    for attempt in range(1, 31):
        try:
            with urllib.request.urlopen(f"{API_URL}/v1/jobs/{job_id}", timeout=5) as res:
                job_data = json.loads(res.read().decode())
                current_status = job_data["status"]
                scorecard = job_data.get("scorecard_data") or {}
                overall_status = scorecard.get("overall_status")
                print(f"    Attempt {attempt}: status is '{current_status}' (overall: {overall_status})")
                if current_status in ("completed", "failed", "review_required"):
                    break
        except Exception as e:
            print(f"    Attempt {attempt}: polling error {e}")
        time.sleep(2)

    print(f"    Final status: {current_status} (overall_status: {overall_status})")
    
    # When expected is "failed", verify that the job finished and marked non_compliant
    if expected_status == "failed":
        if overall_status in ("non_compliant", "failed") or current_status == "failed":
            print(f"✓ Test passed for {sample_filename} (correctly marked as {overall_status}).")
            return
    elif current_status == expected_status:
        print(f"✓ Test passed for {sample_filename}.")
        return

    print(f"ERROR: Expected status '{expected_status}', but got status='{current_status}', overall='{overall_status}'")
    sys.exit(1)


def main() -> None:
    check_ready()
    submit_and_poll("valid_cert.pdf", "completed")
    submit_and_poll("expired_cert.pdf", "failed")
    print("=== All Smoke Tests Passed Successfully ===")


if __name__ == "__main__":
    main()

