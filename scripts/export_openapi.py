"""Export OpenAPI schema definition to openapi.json in a deterministic order."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings
from app.main import create_app

OUTPUT = ROOT / "openapi.json"


def main() -> None:
    # Build app with dev settings so docs and openapi are enabled
    app = create_app(Settings(app_env="dev"))
    schema = app.openapi()

    # Format JSON deterministically with sorted keys and 2-space indentation
    formatted = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(formatted, encoding="utf-8")
    print(f"Exported OpenAPI schema to {OUTPUT} ({len(formatted)} bytes)")


if __name__ == "__main__":
    main()
