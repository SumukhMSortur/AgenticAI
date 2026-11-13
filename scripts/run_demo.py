"""Run the deterministic golden-set scenario used by the local demo gate."""

from __future__ import annotations

import tempfile
from pathlib import Path

from scripts.evaluate_verifier import evaluate_golden_set
from scripts.run_evaluations import GIT_UNAVAILABLE


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ecochain-demo-") as directory:
        report = evaluate_golden_set(
            output_path=Path(directory) / "verifier.json",
            source_git_sha=GIT_UNAVAILABLE,
        )
    verdicts_pass = report["expected_verdict_accuracy"] == 1.0
    escalation_pass = report["escalation_accuracy"] == 1.0
    print(
        "Golden scenario: "
        f"{report['case_count']} cases, "
        f"{report['expected_verdicts_correct']}/{report['expected_verdicts_total']} verdicts, "
        f"{report['escalation_cases_correct']}/{report['escalation_cases_total']} escalations."
    )
    if not verdicts_pass or not escalation_pass:
        print("Demo gate failed: golden scenario results did not meet the 100% acceptance gate.")
        return 1
    print("Demo gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
