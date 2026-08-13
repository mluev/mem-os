from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from sdk.python.memkit_client.client import AuthenticatedClient

ROOT = Path(__file__).resolve().parents[1]


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
    document = json.loads((ROOT / "openapi.json").read_text())
    scheme = document["components"]["securitySchemes"]["APIKeyHeader"]
    assert scheme == {"type": "apiKey", "in": "header", "name": "X-API-Key"}


def test_generated_responses_have_named_fields() -> None:
    document = json.loads((ROOT / "openapi.json").read_text())
    schemas = document["components"]["schemas"]
    assert set(schemas["JobQueuedOut"]["required"]) >= {"job_id", "status"}
    assert set(schemas["MemorySearchOut"]["required"]) >= {
        "memories",
        "used_tokens",
        "policy_id",
    }
