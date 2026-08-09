"""Write the canonical OpenAPI document without starting the service."""

from __future__ import annotations

import json
from pathlib import Path

from memkit.api import app

root = Path(__file__).resolve().parent.parent
(root / "openapi.json").write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
