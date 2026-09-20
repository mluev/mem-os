"""What the generated SDKs are allowed to assume.

The two clients are generated, so nothing in them is hand-checked. What can be
checked is the shape they are generated from and the shape they ship: that the
committed OpenAPI still declares the header the clients send, that the response
models the clients unwrap still carry named fields, and that the TypeScript
package actually contains the declarations its own `types` entry points at --
a pack that omits `dist/schema.d.ts` installs cleanly and fails at `tsc`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from sdk.python.memkit_client.client import AuthenticatedClient

ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads((ROOT / "openapi.json").read_text())


def test_python_authenticated_client_uses_memkit_header() -> None:
    client = AuthenticatedClient(base_url="http://memkit.test", token="secret")
    request = client.get_httpx_client().build_request("GET", "/healthz")
    assert request.headers["X-API-Key"] == "secret"
    assert "Authorization" not in request.headers


def test_typescript_pack_contains_every_referenced_declaration() -> None:
    package = ROOT / "sdk" / "typescript"
    pnpm = shutil.which("pnpm")
    assert pnpm is not None
    subprocess.run(  # noqa: S603
        [pnpm, "build"], cwd=package, check=True, capture_output=True, text=True
    )
    packed = subprocess.run(  # noqa: S603
        [pnpm, "pack", "--pack-destination", tempfile.gettempdir()],
        cwd=package,
        check=True,
        capture_output=True,
        text=True,
    )
    archive_path = Path(packed.stdout.strip().splitlines()[-1])
    try:
        with tarfile.open(archive_path) as archive:
            names = set(archive.getnames())
        assert "package/dist/index.d.ts" in names
        assert "package/dist/schema.d.ts" in names
    finally:
        archive_path.unlink(missing_ok=True)


def test_openapi_declares_api_key_header() -> None:
    scheme = _document()["components"]["securitySchemes"]["APIKeyHeader"]
    assert scheme == {"type": "apiKey", "in": "header", "name": "X-API-Key"}


def test_the_password_door_is_the_only_unauthenticated_v1_write() -> None:
    """A key is not the only credential any more, so a client has to be able to
    reach the login endpoint without one -- and nothing else."""
    document = _document()
    open_writes = sorted(
        path
        for path, methods in document["paths"].items()
        if path.startswith("/v1")
        for method, operation in methods.items()
        if method in {"post", "patch", "put", "delete"} and not operation.get("security")
    )
    assert open_writes == ["/v1/auth/login", "/v1/auth/logout"]


def test_generated_responses_have_named_fields() -> None:
    schemas = _document()["components"]["schemas"]
    assert set(schemas["JobQueuedOut"]["required"]) >= {"job_id", "status"}
    assert set(schemas["MemorySearchOut"]["required"]) >= {
        "memories",
        "used_tokens",
        "policy_id",
    }


def test_a_client_can_see_whether_a_write_still_needs_review() -> None:
    """The whole review loop is invisible to an SDK caller unless the create
    response says which state the memory landed in."""
    schemas = _document()["components"]["schemas"]
    assert "review_status" in schemas["MemoryCreatedOut"]["properties"]
    assert schemas["ReviewIn"]["properties"]["decision"]["enum"] == [
        "confirm",
        "decline",
        "undo",
    ]
