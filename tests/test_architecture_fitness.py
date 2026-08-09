from __future__ import annotations

import json
from pathlib import Path

from memkit.api import app

ROOT = Path(__file__).resolve().parents[1]


def test_retired_workflow_product_cannot_reenter_runtime() -> None:
    forbidden_files = [
        ROOT / "src/memkit/taskboard.py",
        ROOT / "src/memkit/mutate.py",
        ROOT / "web/src/routes/Tasks.tsx",
    ]
    assert not any(path.exists() for path in forbidden_files)
    paths = set(app.openapi()["paths"])
    assert not any("task-board" in path or path.endswith("/tasks") for path in paths)
    package = json.loads((ROOT / "web/package.json").read_text())
    assert not any(name.startswith("@dnd-kit/") for name in package["dependencies"])


def test_generic_core_has_no_retired_domain_columns() -> None:
    # db.py alone contains the compatibility migration and its automatic export.
    for path in (ROOT / "src/memkit").glob("*.py"):
        if path.name == "db.py":
            continue
        text = path.read_text()
        assert "workflow_status" not in text, path
        assert "scope_key" not in text, path
        assert "task_board" not in text, path


def test_generated_openapi_is_current() -> None:
    committed = json.loads((ROOT / "openapi.json").read_text())
    assert committed == app.openapi()
