"""Export the FastAPI OpenAPI schema for frontend client generation."""

import json
from pathlib import Path

from backend.app.main import app

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_OUTPUT_PATH = _PROJECT_ROOT / "frontend" / "openapi.json"


def main() -> None:
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Exported OpenAPI schema to {_OUTPUT_PATH.relative_to(_PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
