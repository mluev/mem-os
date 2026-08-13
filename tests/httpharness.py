"""TestClient harness for the real FastAPI app.

`api.py` had no tests at all, which is how behavioural drift went unnoticed for
weeks: `use_batch` was silently accepted, the mutation lock during reindex was
never exercised, and nothing proved a router was mounted behind the API key.
Those are contract claims, and a doc cannot check them.

What is stubbed and what is not
-------------------------------
The route bodies, the Pydantic validation, the dependency graph and the SQLite
work are all real. Two things are replaced: Qdrant (a dict) and the embedder
(a constant vector), because the real pair needs a container and an ~11 second
torch/MPS model load. `api.lifespan` is swapped rather than patched piecemeal so
startup ordering and `close_all()` on shutdown still run.

Not covered here, deliberately, because all four are decided at import time from
`_startup_settings` and testing them needs `importlib.reload` or a subprocess --
which would register a second `app` object and cause worse problems than the gap:
`docs_url`/`redoc_url` (`expose_docs`), the CORS middleware, and the `/ui` mount.

    .venv/bin/python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

# Belt and braces, and it must happen before memkit.config is imported: `.env`
# sets MEMKIT_DB_PATH to the live database and api.py builds the settings
# singleton at import time. A forgotten patch downstream must not be able to
# open production data.
_HARNESS_TMP = Path(tempfile.mkdtemp(prefix="memkit-http-"))
os.environ["MEMKIT_DB_PATH"] = str(_HARNESS_TMP / "import-time-guard.db")

from fastapi.testclient import TestClient  # noqa: E402

from memkit import api, config  # noqa: E402
from memkit.db import ConnectionPool, ensure_owner, init_db, transaction  # noqa: E402
from tests.fixtures import OWNER, StubEmbedder, StubQdrant  # noqa: E402

TEST_KEY = "test-key"


# The credential fields carry a `validation_alias`, which means pydantic accepts
# ONLY the alias -- `Settings(anthropic_api_key="")` is silently dropped by
# `extra="ignore"` and the value falls through to `.env`. Writing the field name
# here looks right, does nothing, and lets a test make a real billed API call.
# Found the hard way: the first run of this suite called Gemini for real.
_CREDENTIAL_ALIASES = {
    "ANTHROPIC_API_KEY": "",
    "GEMINI_API_KEY": "",
    "GOOGLE_API_KEY": "",
    "GOOGLE_VERTEX_API_KEY": "",
    "VERTEX_PROJECT": "",
    "GOOGLE_CLOUD_PROJECT": "",
    "VERTEX_LOCATION": "",
}


def test_settings(db_path: Path) -> config.Settings:
    """Settings for one test: temp DB, known key, and no judge credentials.

    Init kwargs outrank `.env` in pydantic-settings, so blanking every
    credential alias here is what keeps a test run offline. `assert_offline`
    below is the guard that this actually worked.
    """
    return config.Settings(
        api_key=TEST_KEY,
        api_key_file=None,
        telemetry_hmac_key=TEST_KEY,
        db_path=db_path,
        owner_id=OWNER,
        owner_name="test",
        monthly_cost_limit_usd=1.0,
        **_CREDENTIAL_ALIASES,
    )


def assert_offline(settings: config.Settings) -> None:
    """Fail loudly if any judge credential survived into the test settings.

    Not paranoia: the aliasing above means the obvious way to write
    `test_settings` fails open, and a fifth credential field added later would
    reintroduce it. A test that reaches a paid API is worse than a failing test,
    so this is checked on every setUp rather than trusted once.
    """
    leaked = [
        name
        for name in ("anthropic_api_key", "gemini_api_key", "vertex_project")
        if getattr(settings, name)
    ]
    if leaked or api.judge_configured(settings):
        raise AssertionError(
            "test settings still carry judge credentials "
            f"({leaked or 'judge_configured() is True'}) -- a test would call a "
            "paid API. Blank the field's validation_alias in _CREDENTIAL_ALIASES."
        )


@asynccontextmanager
async def stub_lifespan(app):
    """Mirrors api.lifespan, minus the container and the model load."""
    s = config.get_settings()
    init_db(s.db_path)
    app.state.db = ConnectionPool(s.db_path)
    with transaction(app.state.db()):
        ensure_owner(app.state.db(), s.owner_id, s.owner_name)
    app.state.qdrant = StubQdrant()
    app.state.embedder = StubEmbedder()
    app.state.reindex_lock = threading.Lock()
    app.state.reindex_job = {"status": "idle"}
    app.state.index_dirty = False
    app.state.embedder.load()
    yield
    app.state.db.close_all()


class ApiTestCase(unittest.TestCase):
    """One temp database and one client per test method.

    `patch.object(config, "_settings", ...)` is what redirects the settings:
    `get_settings()` is called directly in 31 places and only once through
    `Depends`, so `dependency_overrides` would reach `require_key` and nothing
    else. `enterContext` guarantees the patches unwind even on error, so a temp
    path cannot leak into a later test module in the same process.
    """

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="memkit-case-"))
        self.db_path = self.tmpdir / "t.db"
        settings = test_settings(self.db_path)
        assert_offline(settings)
        self.enterContext(patch.object(config, "_settings", settings))
        self.enterContext(patch.object(api.app.router, "lifespan_context", stub_lifespan))
        self.client = self.enterContext(TestClient(api.app))
        self.auth = {"X-API-Key": TEST_KEY}

    # --- accessors -------------------------------------------------------

    @property
    def db(self):
        return api.app.state.db()

    @property
    def qdrant(self) -> StubQdrant:
        return api.app.state.qdrant

    def sql(self, query: str, *params):
        return self.db.execute(query, params).fetchall()

    def scalar(self, query: str, *params):
        return self.db.execute(query, params).fetchone()[0]

    # --- seeding ---------------------------------------------------------

    def seed_message(
        self,
        *,
        session_id: str = "s-1",
        role: str = "user",
        content: str = "I always use pnpm, never npm, on every project",
        **kw,
    ) -> int:
        """Create a message through the real endpoint, so the session exists."""
        body = {"session_id": session_id, "role": role, "content": content, **kw}
        r = self.client.post("/v1/messages", json=body, headers=self.auth)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["message_id"]

    def seed_memory(
        self,
        *,
        text: str = "Prefers pnpm over npm on every project",
        kind: str = "preference",
        **kw,
    ) -> str:
        """Create a memory through the real endpoint and return its id."""
        body = {"text": text, "kind": kind, "source_role": "manual", **kw}
        r = self.client.post("/v1/memories", json=body, headers=self.auth)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def set_reindex_running(self) -> None:
        api.app.state.reindex_job = {"status": "running"}

    # --- assertions ------------------------------------------------------

    def assertKeys(self, payload: dict, keys: set[str] | list[str], where: str = ""):
        """Every documented key is present. Extra keys are fine; missing are not."""
        missing = set(keys) - set(payload)
        self.assertFalse(missing, f"{where}missing keys: {sorted(missing)}")


def guarded_operations() -> list[tuple[str, str]]:
    """(method, path) for every route that declares the API key, from OpenAPI.

    Read from `app.openapi()` rather than `app.routes`: FastAPI wraps included
    routers, so walking `app.routes` yields only the handful defined directly on
    `app` and silently misses routes behind included prefixes.
    """
    spec = api.app.openapi()
    out = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if op.get("security"):
                out.append((method.upper(), path))
    return sorted(out)


def open_operations() -> list[tuple[str, str]]:
    """(method, path) for routes with no security requirement."""
    spec = api.app.openapi()
    out = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if not op.get("security"):
                out.append((method.upper(), path))
    return sorted(out)


def sample_path(path: str) -> str:
    """Fill OpenAPI path templates with throwaway values.

    The auth matrix must be rejected at the dependency, before the handler ever
    looks at the id, so any syntactically valid value does the job.
    """
    return (
        path.replace("{memory_id}", "00000000-0000-0000-0000-000000000000")
        .replace("{message_id}", "1")
        .replace("{session_id}", "s-1")
        .replace("{run_id}", "1")
    )
