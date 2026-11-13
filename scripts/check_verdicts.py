"""Print all verdicts for the most recent job."""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"

# Get most recent job
with urllib.request.urlopen(f"{BASE}/v1/jobs") as res:
    jobs = json.loads(res.read())
if not jobs:
    print("No jobs found")
    sys.exit(1)

job = jobs[0] if isinstance(jobs, list) else jobs.get("items", [{}])[0]
job_id = job.get("id") or job.get("job_id")
print(f"Job: {job_id}  Status: {job.get('status')}")
print()

# Get scorecard
try:
    with urllib.request.urlopen(f"{BASE}/v1/jobs/{job_id}/scorecard") as res:
        data = json.loads(res.read())
except Exception as e:
    # Try getting scorecard from job data directly
    data = job.get("scorecard_data", {})
    if not data:
        print(f"Could not fetch scorecard: {e}")
        # Dump the job data to see what's available
        print(json.dumps(job, indent=2, default=str))
        sys.exit(1)

# Print escalation info
esc = data.get("escalation", {})
print(f"Escalated: {esc.get('is_escalated')}  Priority: {esc.get('priority')}")
print(f"Reason: {esc.get('reason')}  Triggered by: {esc.get('triggered_by_rule')}")
verifier_details = esc.get("details", {}).get("verifier", {}).get("details", {})
triggered_rules = verifier_details.get("triggered_rule_ids", [])
print(f"All triggered rules: {triggered_rules}")
print()

# Print each verdict
verdicts = data.get("verdicts", [])
print(f"{'RULE':<16} {'OUTCOME':<12} {'REASON CODE'}")
print("-" * 70)
for entry in verdicts:
    v = entry.get("verdict", entry)
    print(f"{v.get('rule_id','?'):<16} {v.get('outcome','?'):<12} {v.get('reason_code','?')}")
