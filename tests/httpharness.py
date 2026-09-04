"""TestClient harness for the real FastAPI app.

`api.py` had no tests at all, which is how behavioural drift went unnoticed for
weeks: `use_batch` was silently accepted, the mutation lock during reindex was
never exercised, and nothing proved a router was mounted behind the API key.
Those are contract claims, and a doc cannot check them.

What is stubbed and what is not
-------------------------------
The route bodies, the Pydantic validation, the dependency graph, the identity
resolution and the database work are all real. Two things are replaced: Qdrant
(a dict) and the embedder (a constant vector), because the real pair needs a
container and an ~11 second torch/MPS model load. `api.lifespan` is swapped
rather than patched piecemeal so startup ordering and `close_all()` on shutdown
still run.

Every case gets two users. A single-user harness cannot catch the failure this
system most needs to avoid, which is one person's memory reaching another.

Not covered here, deliberately, because all four are decided at import time from
`_startup_settings` and testing them needs `importlib.reload` or a subprocess --
which would register a second `app` object and cause worse problems than the gap:
`docs_url`/`redoc_url` (`expose_docs`), the CORS middleware, and the `/ui` mount.

    .venv/bin/python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import os
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from memkit import api, auth, config, outbox
from memkit.db import ConnectionPool, connect, truncate_all
from tests.fixtures import PASSWORD, StubEmbedder, StubQdrant, seed_team


def fixtures_password() -> str:
    return PASSWORD


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


def test_settings() -> config.Settings:
    """Settings for one test: the test database, and no judge credentials.

    Init kwargs outrank `.env` in pydantic-settings, so blanking every
    credential alias here is what keeps a test run offline. `assert_offline`
    below is the guard that this actually worked.
    """
    return config.Settings(
        telemetry_hmac_key="test-hmac-key-that-is-long-enough-32ch",
        database_url=os.environ["MEMKIT_DATABASE_URL"],
        cookie_secure=False,
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
    settings = config.get_settings()
    app.state.db = ConnectionPool(settings.database_url)
    app.state.qdrant = StubQdrant()
    app.state.embedder = StubEmbedder()
    app.state.embedder.load()
    app.state.index_ready = True
    app.state.index_error = None
    app.state.maintenance = False
    app.state.login_limiter = auth.RateLimiter()

    class _InlineWorker:
        """Drains on wake, so a test sees the index the request implied.

        Production hands this to a background thread; doing it inline keeps
        assertions about what reached the index deterministic.
        """

        def wake(self) -> None:
            with app.state.db.borrow() as conn:
                outbox.drain(conn, app.state.qdrant, app.state.embedder, limit=200)

        def stop(self) -> None:
            pass

    app.state.worker = _InlineWorker()
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
        settings = test_settings()
        assert_offline(settings)
        self.enterContext(patch.object(config, "_settings", settings))
        seeder = connect(settings.database_url)
        truncate_all(seeder)
        self.team = seed_team(seeder)
        self.alice_key = self.team.alice_key
        self.bob_key = self.team.bob_key
        seeder.close()
        self.enterContext(patch.object(api.app.router, "lifespan_context", stub_lifespan))
        self.client = self.enterContext(TestClient(api.app))
        # `auth` stays the default caller so existing single-user assertions
        # read unchanged; `as_bob` is the other side of every isolation claim.
        self.auth = {"X-API-Key": self.team.alice_key}
        self.as_bob = {"X-API-Key": self.team.bob_key}

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
        r = self.client.post("/v1/evidence/events", json=body, headers=self.auth)
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

    def login(self, who: str = "alice") -> dict[str, str]:
        """Sign in with a password and return the header a cookie write needs."""
        r = self.client.post(
            "/v1/auth/login", json={"handle": who, "password": fixtures_password()}
        )
        self.assertEqual(r.status_code, 200, r.text)
        return {"X-Requested-With": "memkit"}

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
        .replace("{user_id}", "00000000-0000-0000-0000-000000000000")
        .replace("{key_id}", "00000000-0000-0000-0000-000000000000")
        .replace("{item_id}", "00000000-0000-0000-0000-000000000000")
        .replace("{retrieval_id}", "00000000-0000-0000-0000-000000000000")
        .replace("{slug}", "no-such-entity")
        .replace("{job_id}", "00000000-0000-0000-0000-000000000000")
        .replace("{alias}", "nobody")
    )
