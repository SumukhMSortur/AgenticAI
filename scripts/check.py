"""Cross-platform check script mirroring `make check`."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if sys.platform == "win32":
    RUFF = ROOT / ".venv" / "Scripts" / "ruff.exe"
    MYPY = ROOT / ".venv" / "Scripts" / "mypy.exe"
    PYTEST = ROOT / ".venv" / "Scripts" / "pytest.exe"
else:
    RUFF = ROOT / ".venv" / "bin" / "ruff"
    MYPY = ROOT / ".venv" / "bin" / "mypy"
    PYTEST = ROOT / ".venv" / "bin" / "pytest"


def run_command(args: list[str], description: str) -> None:
    print(f"\n--- Running: {description} ({' '.join(args)}) ---")
    res = subprocess.run(args, cwd=ROOT)
    if res.returncode != 0:
        print(f"FAILED: {description} with exit code {res.returncode}")
        sys.exit(res.returncode)


def main() -> None:
    print("Executing EcoChain Copilot verification pipeline...")
    run_command([str(RUFF), "check", "backend"], "Ruff linter")
    run_command([str(MYPY), "backend/app"], "Mypy type checking")
    run_command([str(PYTEST), "backend/tests", "-v"], "Pytest test suite")
    print("\nAll checks passed successfully! (make check equivalent: GREEN)")


if __name__ == "__main__":
    main()
