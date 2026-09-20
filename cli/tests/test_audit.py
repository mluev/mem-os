"""Regressions found by the CLI audit, independent of live deployments."""

import json
import subprocess
import time
from types import SimpleNamespace

import httpx
import pytest
from test_cli import clean_config, invoke, managed_worker, mock_client  # noqa: F401

from memos_cli import cli, config, server
from memos_cli.client import Client
from memos_cli.errors import ClientError

pytestmark = pytest.mark.usefixtures("clean_config")


def saved_server():
    entry = {
        "url": "http://127.0.0.1:18079",
        "key": "device-secret",
        "server": {
            "host": "fixture-host",
            "directory": "/srv/memos",
            "port": 18078,
            "local_port": 18079,
            "tunnel": True,
        },
    }
    config.save({"default": "work", "connections": {"work": entry}})
    return entry


def test_reinstall_preserves_named_connection(monkeypatch, capsys, tmp_path):
    original = saved_server()
    password = tmp_path / "password"
    password.write_text("fixture-password")
    monkeypatch.setattr(server, "remote", lambda *a: {"installed": True, "existing": True})
    tunnels = []
    monkeypatch.setattr(server, "ensure_tunnel", lambda s: tunnels.append(s.copy()))
    code, _, _ = invoke(
        capsys,
        "server",
        "install",
        "--name",
        "work",
        "--image",
        "memos:old",
        "--password-file",
        str(password),
    )
    assert code == 0
    assert config.load()["connections"]["work"] == original
    assert tunnels == [original["server"]]


def test_reinstall_rejects_conflicting_remote_port(monkeypatch, capsys, tmp_path):
    original = saved_server()
    password = tmp_path / "password"
    password.write_text("fixture-password")
    monkeypatch.setattr(server, "remote", lambda *a: pytest.fail("must reject before mutation"))
    code, _, _ = invoke(
        capsys,
        "server",
        "install",
        "--name",
        "work",
        "--image",
        "memos:old",
        "--remote-port",
        "9000",
        "--password-file",
        str(password),
    )
    assert code == 2
    assert config.load()["connections"]["work"] == original


@pytest.mark.parametrize("apply", [False, True])
def test_import_limit_reaches_server(tmp_path, monkeypatch, apply):
    worker = managed_worker(tmp_path)
    calls = []
    monkeypatch.setattr(worker, "run", lambda argv, **kw: calls.append(argv) or "report")
    worker.perform(
        {
            "action": "import-claude-code",
            "directory": str(tmp_path),
            "path": str(tmp_path / "imports/session"),
            "limit": 3,
            "apply": apply,
        }
    )
    assert calls[-1][-2:] == ["--limit", "3"]
    assert ("--dry-run" in calls[-1]) is not apply


@pytest.mark.parametrize(
    "argv",
    [
        ["doctor", "--load-model"],
        ["drain-index", "--retry-now"],
        ["backup", "create", "--kind", "daily"],
    ],
)
def test_server_options_discoverable_and_forwarded(tmp_path, monkeypatch, argv):
    args = cli.parser_tree().parse_args(["server", *argv])
    worker = managed_worker(tmp_path)
    calls = []
    monkeypatch.setattr(worker, "run", lambda cmd, **kw: calls.append(cmd) or '{"id":"b"}')
    worker.perform({**vars(args), "directory": str(tmp_path)})
    flag = next(a for a in argv if a.startswith("--"))
    assert flag in calls[-1]


@pytest.mark.parametrize(
    "value",
    [[], {"connections": []}, {"connections": {"x": None}}, {"connections": {}, "default": []}],
)
def test_invalid_config_has_stable_error(tmp_path, capsys, value):
    config.private_write(config.config_dir() / "connections.json", json.dumps(value))
    code, out, _ = invoke(capsys, "status")
    assert code == 2 and out["error"]["code"] == "invalid_input"


@pytest.mark.parametrize("response", [[], None, {"job": []}])
def test_malformed_job_response_is_protocol_error(monkeypatch, capsys, response):
    mock_client(monkeypatch, lambda req: httpx.Response(200, content=json.dumps(response)))
    code, out, _ = invoke(capsys, "jobs", "get", "one", "--wait", "1")
    assert code == 7 and out["error"]["code"] == "protocol"


@pytest.mark.parametrize(
    "command",
    [
        ["server", "tunnel"],
        ["server", "tunnel", "--close"],
        ["server", "backup", "download", "one"],
    ],
)
def test_ssh_timeout_is_structured(monkeypatch, capsys, tmp_path, command):
    saved_server()
    target = tmp_path / "backup"
    target.write_text("original")
    if "download" in command:
        command += ["--output", str(target)]
        monkeypatch.setattr(server, "remote", lambda *a: {"path": "/backups/one", "sha256": "x"})

    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("ssh", 15)

    monkeypatch.setattr(server.subprocess, "run", timeout)
    code, out, _ = invoke(capsys, *command)
    assert code == 8 and out["error"]["code"] == "timeout"
    assert target.read_text() == "original"
    assert not list(tmp_path.glob(".memos-backup-*"))


def test_option_terminator_preserves_literal_text(monkeypatch, capsys):
    seen = []
    mock_client(
        monkeypatch,
        lambda req: seen.append(json.loads(req.content)) or httpx.Response(200, json={}),
    )
    assert cli.main(["--json", "remember", "--", "--json"]) == 0
    capsys.readouterr()
    assert seen == [{"text": "--json", "kind": "fact", "source_role": "manual"}]


@pytest.mark.parametrize("flag,value", [("--timeout", "nan"), ("--wait", "nan"), ("--wait", "inf")])
def test_nonfinite_budgets_rejected_before_connect(monkeypatch, capsys, flag, value):
    monkeypatch.setattr(cli, "connect", lambda *a: pytest.fail("must not connect"))
    code, _, _ = invoke(capsys, "search", "decision", flag, value)
    assert code == 2


def test_explicit_null_overrides_json_body(monkeypatch, capsys):
    seen = []
    mock_client(
        monkeypatch,
        lambda req: seen.append(json.loads(req.content)) or httpx.Response(200, json={}),
    )
    code, _, _ = invoke(
        capsys,
        "memories",
        "update",
        "one",
        "--expected-revision",
        "1",
        "--data",
        '{"context":{"x":1}}',
        "--context",
        "null",
    )
    assert code == 0 and seen[0]["context"] is None


@pytest.mark.parametrize(
    "command",
    [["health"], ["ready"], ["auth", "login", "--handle", "alice", "--password", "password"]],
)
def test_public_requests_open_tunnel(monkeypatch, capsys, command):
    saved_server()
    opened, seen = [], []
    monkeypatch.setattr(server, "ensure_tunnel", lambda s: opened.append(s))

    def make(url, key="", **kw):
        return Client(
            url,
            key,
            transport=httpx.MockTransport(
                lambda req: seen.append(req) or httpx.Response(200, json={})
            ),
            **kw,
        )

    monkeypatch.setattr(cli, "Client", make)
    assert invoke(capsys, *command)[0] == 0
    assert len(opened) == 1
    assert "X-API-Key" not in seen[0].headers


def test_error_response_read_is_bounded():
    class EndlessError(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(8):
                yield b"x" * 1024
            pytest.fail("client must stop after 8192 error bytes")

    client = Client(
        "https://memory.example",
        transport=httpx.MockTransport(lambda req: httpx.Response(503, stream=EndlessError())),
    )
    with pytest.raises(ClientError) as failure:
        client.get("/healthz")
    assert failure.value.exit_code == 7


def test_pagination_budget_includes_first_request(monkeypatch, capsys):
    now, seen = [0.0], []
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    def handle(request):
        seen.append(request)
        now[0] += 2
        return httpx.Response(200, json={"items": [{"id": "one"}] if len(seen) == 1 else []})

    mock_client(monkeypatch, handle)
    code, out, _ = invoke(capsys, "memories", "list", "--all", "--limit", "1", "--wait", "1")
    assert code == 8 and out["error"]["code"] == "timeout"
    assert len(seen) == 1
    assert seen[0].extensions["timeout"]["read"] <= 1


def test_failed_doctor_preserves_diagnostics(tmp_path, monkeypatch):
    worker = managed_worker(tmp_path)
    report = {
        "ok": False,
        "checks": [
            {
                "name": "database",
                "ok": False,
                "detail": {"error": "postgres://user:private@host/db"},
            }
        ],
    }
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout=json.dumps(report), stderr="secret diagnostic noise"
        ),
    )
    with pytest.raises(RuntimeError) as failure:
        worker.perform({"action": "doctor", "directory": str(tmp_path)})
    assert "database" in str(failure.value)
    assert "private" not in str(failure.value)
    assert "secret diagnostic noise" not in str(failure.value)


@pytest.mark.parametrize(
    "command", list(__import__("memos_cli.registry", fromlist=["ROUTES"]).ROUTES)
)
def test_every_api_operation_serializes_all_fields(command, monkeypatch, capsys, tmp_path):
    """Use the canonical server schema as the independent wire-contract oracle."""
    from pathlib import Path
    from urllib.parse import quote

    from memos_cli import registry

    document = json.loads((Path(__file__).resolve().parents[2] / "openapi.json").read_text())
    method, path = registry.ROUTES[command]
    operation = document["paths"][path][method.lower()]

    def resolve(schema):
        if "$ref" in schema:
            return resolve(document["components"]["schemas"][schema["$ref"].split("/")[-1]])
        if "anyOf" in schema:
            return resolve(next(s for s in schema["anyOf"] if s.get("type") != "null"))
        return schema

    def sample(schema):
        schema = resolve(schema)
        if "enum" in schema:
            return schema["enum"][0]
        kind = schema.get("type", "object")
        if kind == "boolean":
            return False
        if kind in {"number", "integer"}:
            return (int if kind == "integer" else float)(schema.get("minimum", 1))
        if kind == "array":
            return [sample(schema["items"])]
        if kind == "object":
            props = schema.get("properties")
            return {k: sample(v) for k, v in props.items()} if props else {"audit": True}
        return "audit-value"

    args, expected_query = command.split(), {}
    for parameter in operation.get("parameters", []):
        name = parameter["name"]
        if parameter["in"] == "path":
            value = "id with spaces"
            args.append(value)
            path = path.replace("{" + name + "}", quote(value, safe=""))
        elif parameter["in"] == "query":
            value = sample(parameter["schema"])
            expected_query[name] = str(value).lower() if isinstance(value, bool) else str(value)
            flag = "--" + name.replace("_", "-")
            args += ["--no-" + name.replace("_", "-")] if value is False else [flag, str(value)]
    body_schema = resolve(
        operation.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    expected_body = {}
    for name, schema in body_schema.get("properties", {}).items():
        value = (
            "ERASE ALL DATA" if name == "confirm" and command == "users erase" else sample(schema)
        )
        expected_body[name] = value
        if value is False:
            args.append("--no-" + name.replace("_", "-"))
        else:
            encoded = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
            args.append("--" + name.replace("_", "-") + "=" + encoded)
    if command == "jobs download":
        args += ["--output", str(tmp_path / "export")]
    seen = []

    def factory(url, key="", **kw):
        return Client(
            url,
            key,
            transport=httpx.MockTransport(
                lambda request: seen.append(request) or httpx.Response(200, json={"items": []})
            ),
            **kw,
        )

    config.save(
        {
            "default": "test",
            "connections": {"test": {"url": "https://memory.example", "key": "test-key"}},
        }
    )
    monkeypatch.setattr(cli, "Client", factory)
    code, out, _ = invoke(capsys, *args)
    assert code == 0, out
    assert len(seen) == 1
    request = seen[0]
    assert request.method == method
    assert request.url.raw_path.split(b"?")[0].decode() == path
    assert dict(request.url.params) == expected_query
    assert (json.loads(request.content) if request.content else {}) == expected_body


def test_remote_protocol_and_diagnostic_details(monkeypatch):
    monkeypatch.setattr(
        server,
        "ssh",
        lambda *a, **kw: (
            '{"ok":false,"error":"failed","details":{"checks":[{"name":"database","ok":false}]}}'
        ),
    )
    with pytest.raises(ClientError) as failure:
        server.remote({"host": "fixture", "directory": "/srv/memos"}, {"action": "doctor"})
    assert failure.value.payload()["details"]["checks"][0]["name"] == "database"


@pytest.mark.parametrize(
    "value", ["[]", "null", "not JSON", '{"ok":true,"data":null}', '{"ok":false,"error":[]}']
)
def test_bad_ssh_envelope_has_protocol_error(monkeypatch, value):
    monkeypatch.setattr(server, "ssh", lambda *a, **kw: value)
    with pytest.raises(ClientError) as failure:
        server.remote({"host": "fixture", "directory": "/srv/memos"}, {"action": "status"})
    assert failure.value.code == "protocol"


def test_remote_script_runs_without_client_imports(monkeypatch, tmp_path):
    import shlex
    import sys

    def local_script(host, command, **kw):
        words = shlex.split(command)
        result = subprocess.run(
            [sys.executable, "-I", "-c", words[2]],
            input=kw["input"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    monkeypatch.setattr(server, "ssh", local_script)
    with pytest.raises(ClientError, match="not a CLI-managed deployment"):
        server.remote({"host": "fixture", "directory": str(tmp_path)}, {"action": "status"})


@pytest.mark.parametrize("flag", ["--text=--json", "--text=--url", "--text=--text"])
def test_explicit_flag_like_text_is_literal(monkeypatch, capsys, flag):
    seen = []
    mock_client(
        monkeypatch,
        lambda req: seen.append(json.loads(req.content)) or httpx.Response(200, json={}),
    )
    code, _, _ = invoke(capsys, "memories", "update", "one", "--expected-revision", "1", flag)
    assert code == 0 and seen[0]["text"] == flag.split("=", 1)[1]


@pytest.mark.parametrize(
    "value", ["memkit=[]", "[memkit]\nconnection=[]", '[memkit]\ncapture="false"']
)
def test_bad_repository_configuration(tmp_path, capsys, value):
    (tmp_path / ".memkit.toml").write_text(value)
    code, out, _ = invoke(capsys, "status")
    assert code == 2 and "traceback" not in str(out).lower()


def test_snapshot_drift_fails_before_writes(tmp_path, monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "tools/sync_cli_assets.py"
    spec = importlib.util.spec_from_file_location("sync_assets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "snapshot"

    def drifted_outputs():
        yield target, "must not be written"
        raise RuntimeError("CLI snapshot source changed")

    monkeypatch.setattr(module, "outputs", drifted_outputs)
    monkeypatch.setattr(sys, "argv", ["sync_cli_assets.py"])
    with pytest.raises(RuntimeError, match="source changed"):
        module.main()
    assert not target.exists()


def test_remote_reinstall_conflict_precedes_docker(tmp_path, monkeypatch):
    worker = managed_worker(tmp_path)
    monkeypatch.setattr(worker, "run", lambda *a, **kw: pytest.fail("no Docker mutation"))
    with pytest.raises(RuntimeError, match="remote-port"):
        worker.perform(
            {
                "action": "install",
                "directory": str(tmp_path),
                "image": "memos:old",
                "remote_port": 9000,
            }
        )


@pytest.mark.parametrize(
    "response", [{"blocks": []}, {"blocks": {"facts": [None]}}, {"items": [None]}]
)
def test_bad_response_cannot_crash_text_output(monkeypatch, capsys, response):
    mock_client(monkeypatch, lambda req: httpx.Response(200, json=response))
    assert cli.main(["profile", "--text"]) == 7
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "target,filename,value",
    [
        ("claude", "settings.json", "[]"),
        ("claude", "settings.json", '{"hooks":{"Stop":null}}'),
        ("hermes", "config.yaml", "plugins: []"),
    ],
)
def test_bad_agent_config_rejected_before_install(tmp_path, capsys, target, filename, value):
    home = tmp_path / "agent"
    home.mkdir()
    (home / filename).write_text(value)
    code, _, _ = invoke(capsys, "agents", "install", target, "--home", str(home))
    assert code == 2
    assert (home / filename).read_text() == value
    assert not (home / "skills/mem-os/SKILL.md").exists()


def test_setup_reopens_saved_tunnel(monkeypatch, capsys):
    original = saved_server()
    opened = []
    monkeypatch.setattr(server, "ensure_tunnel", lambda s: opened.append(s))
    monkeypatch.setattr(
        cli,
        "Client",
        lambda url, key="", **kw: Client(
            url,
            key,
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json={"handle": "alice"})
            ),
            **kw,
        ),
    )
    assert invoke(capsys, "setup", "--name", "work")[0] == 0
    assert opened == [original["server"]]


def test_export_bad_job_id_is_protocol_failure(monkeypatch, capsys, tmp_path):
    mock_client(monkeypatch, lambda req: httpx.Response(200, json={"job": []}))
    code, out, _ = invoke(capsys, "export", "--output", str(tmp_path / "export"))
    assert code == 7 and out["error"]["code"] == "protocol"
