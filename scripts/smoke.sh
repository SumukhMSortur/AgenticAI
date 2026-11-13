#!/usr/bin/env bash
set -euo pipefail

API_URL="${ECOCHAIN_API_URL:-http://127.0.0.1:8000}"
SAMPLES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../samples" && pwd)"

echo "=== EcoChain Copilot End-to-End Smoke Test ==="
echo "Testing API at: $API_URL"

# Test 1: Healthcheck
echo "--> Checking API readiness (/readyz)..."
curl -sf "$API_URL/readyz" > /dev/null || { echo "ERROR: API is not ready"; exit 1; }
echo "✓ API is ready."

# Helper function to submit and poll a job
run_job() {
  local sample_file="$1"
  local expected_status="$2"
  local sample_path="$SAMPLES_DIR/$sample_file"

  echo "--> Submitting $sample_file (expected: $expected_status)..."
  if [ ! -f "$sample_path" ]; then
    echo "ERROR: Sample file not found at $sample_path"
    exit 1
  fi

  local submit_res
  submit_res=$(curl -s -X POST "$API_URL/v1/jobs" \
    -F "assessment_date=2024-07-01" \
    -F "query=Assess $sample_file" \
    -F "files=@$sample_path;type=application/pdf")

  local job_id
  job_id=$(echo "$submit_res" | grep -o '"id":"[^"]*' | cut -d'"' -f4)
  if [ -z "$job_id" ]; then
    echo "ERROR: Failed to get job_id from response: $submit_res"
    exit 1
  fi
  echo "    Job created with ID: $job_id"

  # Poll until terminal state
  local max_attempts=30
  local attempt=1
  local current_status="queued"
  while [ $attempt -le $max_attempts ]; do
    local job_res
    job_res=$(curl -s "$API_URL/v1/jobs/$job_id")
    current_status=$(echo "$job_res" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
    echo "    Attempt $attempt: status is '$current_status'"

    if [ "$current_status" = "completed" ] || [ "$current_status" = "failed" ] || [ "$current_status" = "review_required" ]; then
      break
    fi
    sleep 2
    attempt=$((attempt + 1))
  done

  echo "    Final status: $current_status"
  if [ "$current_status" != "$expected_status" ]; then
    echo "ERROR: Expected status '$expected_status', but got '$current_status'"
    exit 1
  fi
  echo "✓ Test passed for $sample_file."
}

# Run smoke checks
run_job "valid_cert.pdf" "completed"
run_job "expired_cert.pdf" "failed"

echo "=== All Smoke Tests Passed Successfully ==="

