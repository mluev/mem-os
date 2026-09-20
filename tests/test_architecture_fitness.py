"""Structural invariants nothing else can check.

A fitness test is not a unit test: it makes a claim about the shape of the
codebase that no single behaviour would reveal. The three claims here have all
been violated before. A retired subsystem came back as a stub because its
router was still mounted. A generated artefact drifted from its generator and
was read as authoritative for weeks. And the single-owner model this service
was rebuilt to leave behind is one forgotten `owner_id` away from returning as
a cross-tenant read.

Written against the AST and the route graph rather than the source text: a
regex over handler bodies would pass on a handler that mentions `principal` in
a comment, and fail on one that spells its SQL across two lines.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

from fastapi.routing import APIRoute

from memkit.api import app, require_admin

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "memkit"


def _api_routes():
    """Every APIRoute, including those moved into the domain routers.

    `mount_domain_routers` re-parents the endpoints, and FastAPI wraps each
    included router in an opaque object, so `app.routes` alone reports four
    routes and misses sixty. Walking `app.routes` directly is the mistake this
    helper exists to prevent.
    """
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        if isinstance(route, APIRoute):
            yield route
            continue
        nested = getattr(route, "original_router", None)
        stack.extend(getattr(nested or route, "routes", []) or [])


def _dependencies(dependant):
    yield dependant.call
    for sub in dependant.dependencies:
        yield from _dependencies(sub)


# ---------------------------------------------------------------------------
# Retired subsystems


def test_retired_modules_cannot_reappear() -> None:
    """Each of these was deleted with the single-machine product it belonged to.

    `platform.py` (records, namespaces, collections, links) was a second data
    model beside memory; `replay.py`, `release.py`, `evaluations.py`,
    `policy_sweep.py` and `benchmark.py` were the improvement program built
    around a database one person owned.
    """
    retired = [
        "platform.py",
        "replay.py",
        "release.py",
        "evaluations.py",
        "policy_sweep.py",
        "benchmark.py",
        "taskboard.py",
        "mutate.py",
    ]
    present = [name for name in retired if (PACKAGE / name).exists()]
    assert present == [], present
    routers = [
        name for name in ("platform.py", "replay.py") if (PACKAGE / "routers" / name).exists()
    ]
    assert routers == []


def test_retired_endpoints_are_not_in_the_public_contract() -> None:
    paths = set(app.openapi()["paths"])
    forbidden = [
        path
        for path in paths
        if path.startswith(("/v1/namespaces", "/v1/replay-batches", "/v1/records"))
        or "task-board" in path
        or path.endswith("/tasks")
    ]
    assert forbidden == []


def test_only_the_legacy_importer_speaks_sqlite() -> None:
    """SQLite is a one-way door out of the old build, not a supported backend.

    `importers/sqlite_v6.py` reads a v6 file once and writes Postgres. Anywhere
    else, an `import sqlite3` means a code path that cannot see a team.
    """
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.relative_to(PACKAGE) == Path("importers/sqlite_v6.py"):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "sqlite3" for a in node.names):
                offenders.append(str(path.relative_to(ROOT)))
            if isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], offenders


def test_the_single_owner_column_survives_only_as_history() -> None:
    """`owner_id` in code would be a scope predicate that ignores the team.

    db.py's module docstring explains why the column is gone, and that prose is
    worth keeping: the reason a schema was replaced outlives the schema.
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text())
        # A bare string statement is prose: a docstring, or a comment written
        # as one. Every other string literal is data the code acts on.
        prose = {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "owner_id" in node.value
                and id(node) not in prose
            ):
                offenders.append(f"{path.name}: literal {node.value[:40]!r}")
            for attribute in ("id", "arg", "attr", "name"):
                value = getattr(node, attribute, None)
                if isinstance(value, str) and "owner_id" in value:
                    offenders.append(f"{path.name}: identifier {value}")
    assert offenders == [], offenders


# ---------------------------------------------------------------------------
# Authorization surface


# `/v1/auth/logout` is deliberately open: revoking a cookie must work when the
# session behind it has already expired, and the handler reads nothing but that
# cookie. `/healthz` and `/readyz` are probes, `/v1/auth/login` is the door.
UNAUTHENTICATED = {
    ("GET", "/healthz"),
    ("GET", "/readyz"),
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/logout"),
}


def test_every_operation_declares_who_may_call_it() -> None:
    open_operations = {
        (method.upper(), path)
        for path, methods in app.openapi()["paths"].items()
        for method, operation in methods.items()
        if not operation.get("security")
    }
    assert open_operations == UNAUTHENTICATED


# `/v1/admin` is a dashboard grouping, not an authorization boundary. These
# operations answer for the whole instance to an administrator and for the
# caller alone to anyone else, which is stricter than admin-only would be:
# admin-only would deny an ordinary user their own sessions and their own
# spend. Each entry narrows by `principal` in its body, which the scope-safety
# walk below verifies independently.
PRINCIPAL_SCOPED = {
    ("GET", "/v1/users"),  # you cannot name a teammate as a subject unseen
    ("POST", "/v1/users/{user_id}/erase"),  # a user may always erase themselves
    ("POST", "/v1/admin/consolidate"),  # every scope for an admin, yours otherwise
    ("GET", "/v1/admin/sessions"),
    ("GET", "/v1/admin/sessions/{session_id}/messages"),
    ("GET", "/v1/admin/sessions/{session_id}/memories"),
    ("GET", "/v1/admin/judge-runs"),
    ("GET", "/v1/admin/judge-runs/{run_id}"),
    ("GET", "/v1/admin/metrics"),
    # The statistics panels narrow by principal rather than requiring an
    # administrator: a member's own volume, latency and review backlog are
    # their own business, and locking them out would leave them unable to see
    # whether their agent is working. The one panel that reports on other
    # people, /v1/admin/stats/users, is admin-only and so is absent here.
    ("GET", "/v1/admin/stats/memories"),
    ("GET", "/v1/admin/stats/pipeline"),
    ("GET", "/v1/admin/stats/retrieval"),
    ("GET", "/v1/admin/stats/review"),
    ("GET", "/v1/admin/stats/entities"),
}


def test_administrative_operations_are_guarded_or_narrowed() -> None:
    """Read from the dependency graph, never from the source text.

    A handler can name `require_admin` in a docstring and still be reachable by
    anyone; only what FastAPI resolves decides who gets in.
    """
    unguarded = set()
    for route in _api_routes():
        if not route.path.startswith(("/v1/admin", "/v1/users")):
            continue
        guarded = require_admin in set(_dependencies(route.dependant))
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if not guarded and (method, route.path) not in PRINCIPAL_SCOPED:
                unguarded.add((method, route.path))
    assert unguarded == set(), unguarded


def test_the_principal_scoped_allowance_has_no_stale_entries() -> None:
    """An entry left behind after a route becomes admin-only silently widens it."""
    live = {
        (method, route.path)
        for route in _api_routes()
        for method in route.methods - {"HEAD", "OPTIONS"}
        if require_admin not in set(_dependencies(route.dependant))
    }
    assert live >= PRINCIPAL_SCOPED, PRINCIPAL_SCOPED - live


# ---------------------------------------------------------------------------
# Scope safety


SCOPED_TABLES = ("memories", "sessions", "messages", "judge_runs", "retrieval_runs")
_TABLE_SQL = re.compile(
    rf"\b(?:from|join|update|into)\s+(?:{'|'.join(SCOPED_TABLES)})\b", re.IGNORECASE
)

# Helpers that receive an already-authorised scope list instead of resolving
# one. Empty today: every function in api.py that touches a scoped table takes
# the principal itself. An entry here is a promise that the caller checked.
SCOPE_ARGUMENT_HELPERS: dict[str, str] = {}


def test_every_handler_touching_a_scoped_table_names_the_principal() -> None:
    """The one bug class this system cannot survive is one person's memory
    reaching another. Every scoped table is read through `principal.scopes()`
    or a `principal.user_id` predicate; a query that mentions neither is either
    a leak or a handler that forgot which team it was serving.
    """
    trees = [ast.parse(path.read_text()) for path in (PACKAGE / "routers").glob("*.py")]
    offenders: list[str] = []
    for node in (node for tree in trees for node in tree.body):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        touches = any(
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and _TABLE_SQL.search(child.value)
            for child in ast.walk(node)
        )
        if not touches or node.name in SCOPE_ARGUMENT_HELPERS:
            continue
        names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        names |= {arg.arg for arg in node.args.args + node.args.kwonlyargs}
        if "principal" not in names:
            offenders.append(node.name)
    assert offenders == [], offenders


def test_the_scope_helper_allowance_has_no_stale_entries() -> None:
    defined = {
        node.name
        for path in (PACKAGE / "routers").glob("*.py")
        for node in ast.parse(path.read_text()).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert set(SCOPE_ARGUMENT_HELPERS) <= defined, set(SCOPE_ARGUMENT_HELPERS) - defined


# ---------------------------------------------------------------------------
# Generated artefacts


def test_generated_openapi_is_current() -> None:
    committed = json.loads((ROOT / "openapi.json").read_text())
    assert committed == app.openapi(), "run uv run python tools/export_openapi.py"


def test_documentation_contracts_hold() -> None:
    """Documented values that are derived from code must match it.

    The prompt-versions block in the experiments notebook claimed a registry of
    v2-v6 and consolidator c1 long after the code moved to v7/v8 and c2, because
    the generator for that region had been lost while the marker survived. A
    stale generated block is worse than no block: it reads as authoritative.
    """
    # Loaded by path: `tools` is a namespace package, so a plain import
    # resolves differently depending on what ran before this test.
    spec = importlib.util.spec_from_file_location(
        "memkit_docblocks", ROOT / "tools" / "docblocks.py"
    )
    assert spec and spec.loader
    docblocks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(docblocks)

    assert docblocks.check() == []
