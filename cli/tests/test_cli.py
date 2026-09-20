import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from memos_cli import cli, config, registry
from memos_cli.client import Client
from memos_cli.errors import ClientError


@pytest.fixture(autouse=True)
def clean_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMOS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for key in (
        "MEMOS_CONNECTION",
        "MEMOS_URL",
        "MEMOS_API_KEY",
        "MEMKIT_BASE_URL",
        "MEMKIT_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def configured():
    config.save(
        {
            "default": "hosted",
            "connections": {"hosted": {"url": "https://memory.example", "key": "secret-key"}},
        }
    )


def mock_client(monkeypatch, handler):
    def make(options):
        return Client(
            "https://memory.example", "secret-key", transport=httpx.MockTransport(handler)
        )

    monkeypatch.setattr(cli, "connect", make)


def invoke(capsys, *args):
    code = cli.main([*args, "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_every_operation_has_a_command_and_snapshot_is_current():
    root = Path(__file__).resolve().parents[2]
    actual = json.loads((root / "openapi.json").read_text())
    assert registry.spec() == actual
    expected = {
        (m.upper(), path)
        for path, ops in actual["paths"].items()
        for m in ops
        if m in {"get", "post", "put", "patch", "delete"}
    }
    assert set(registry.ROUTES.values()) == expected
    assert len(set(registry.ROUTES.values())) == len(registry.ROUTES)
    cli.parser_tree()


def test_remember_and_search_preserve_provenance_and_sources(monkeypatch, capsys):
    seen = []

    def handle(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(
            200,
            json={"memories": []}
            if "search" in request.url.path
            else {"id": "m1", "review_status": "confirmed"},
        )

    mock_client(monkeypatch, handle)
    assert invoke(capsys, "remember", "Uses pnpm")[0] == 0
    assert seen[-1][1] == {"text": "Uses pnpm", "kind": "fact", "source_role": "manual"}
    assert invoke(capsys, "remember", "Might prefer npm", "--source-role", "agent")[0] == 0
    assert seen[-1][1]["source_role"] == "agent"
    code, out, _ = invoke(capsys, "search", "package manager", "--include-sources")
    assert code == 0 and out["data"]["memories"] == []
    assert seen[-1][1]["include_sources"] is True


def test_update_reads_revision_and_does_not_retry_conflicts(monkeypatch, capsys):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"memory": {"revision": 4}})
        assert json.loads(request.content) == {"text": "new decision", "expected_revision": 4}
        return httpx.Response(409, json={"detail": "stale revision"})

    mock_client(monkeypatch, handle)
    code, out, _ = invoke(capsys, "memories", "update", "m1", "--text", "new decision")
    assert code == 6 and out["error"]["code"] == "conflict"
    assert [r.method for r in requests] == ["GET", "PATCH"]


def test_structured_input_and_pagination(monkeypatch, capsys, tmp_path):
    path = tmp_path / "body.json"
    path.write_text(
        json.dumps(
            {"text": "literal $(anything) `nothing`", "kind": "fact", "source_role": "manual"}
        )
    )
    seen = []

    def handle(request):
        seen.append(request)
        if request.method == "POST":
            assert json.loads(request.content)["text"] == "literal $(anything) `nothing`"
            return httpx.Response(201, json={"id": "saved"})
        page = [{"id": "one"}] if request.url.params.get("offset", "0") == "0" else []
        return httpx.Response(200, json={"items": page})

    mock_client(monkeypatch, handle)
    assert invoke(capsys, "memories", "create", "--data", "@" + str(path))[0] == 0
    code, out, _ = invoke(capsys, "memories", "list", "--all", "--limit", "1")
    assert code == 0 and out["data"]["items"] == [{"id": "one"}]
    assert seen[-1].url.params["offset"] == "1"


def test_config_precedence_and_permissions(tmp_path, monkeypatch):
    configured()
    settings = config.load()
    settings["connections"]["project"] = {"url": "https://project.example", "key": "project-key"}
    config.save(settings)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".memkit.toml").write_text('[memkit]\nconnection="project"\nentity="work"\n')
    assert config.resolve()["name"] == "project"
    monkeypatch.setenv("MEMOS_CONNECTION", "hosted")
    assert config.resolve()["name"] == "hosted"
    assert config.resolve("project")["key"] == "project-key"
    monkeypatch.setenv("MEMOS_URL", "https://override.example")
    assert config.resolve()["url"] == "https://override.example"
    assert config.resolve(url="https://explicit.example")["url"] == "https://explicit.example"
    assert (config.config_dir() / "connections.json").stat().st_mode & 0o077 == 0


def test_setup_login_mints_key_discards_session_and_never_prints_secret(
    monkeypatch, capsys, tmp_path
):
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path == "/v1/auth/login":
            assert "X-API-Key" not in request.headers
            return httpx.Response(
                200,
                json={"user": {}},
                headers={"Set-Cookie": "memkit_session=session-token; Secure; HttpOnly; Path=/"},
            )
        if request.url.path == "/v1/api-keys":
            assert request.headers["X-Requested-With"] == "memkit"
            assert "memkit_session=session-token" in request.headers["Cookie"]
            return httpx.Response(201, json={"secret": "new-secret", "id": "key-id"})
        if request.url.path == "/v1/auth/logout":
            return httpx.Response(200, json={"ok": True})
        assert request.headers["X-API-Key"] == "new-secret"
        assert "Cookie" not in request.headers
        return httpx.Response(200, json={"user": {"handle": "alice"}})

    original = Client
    monkeypatch.setattr(
        cli,
        "Client",
        lambda url, key, **kw: original(url, key, transport=httpx.MockTransport(handle), **kw),
    )
    password = tmp_path / "password"
    password.write_text("a-long-password")
    code, out, _ = invoke(
        capsys,
        "setup",
        "--url",
        "https://memory.example",
        "--handle",
        "alice",
        "--password-file",
        str(password),
    )
    assert code == 0
    assert "new-secret" not in json.dumps(out)
    assert config.resolve()["key"] == "new-secret"
    assert len(seen) == 4


def test_noninteractive_setup_requires_inputs_and_no_network(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    code, out, _ = invoke(capsys, "setup", "--url", "https://memory.example")
    assert code == 2 and "--api-key-file" in out["error"]["message"]


@pytest.mark.parametrize(
    "status,exit_code", [(401, 3), (403, 4), (404, 5), (409, 6), (429, 7), (503, 7)]
)
def test_stable_errors_and_key_redaction(monkeypatch, capsys, status, exit_code):
    mock_client(monkeypatch, lambda request: httpx.Response(status, json={"detail": "secret-key"}))
    code, out, _ = invoke(capsys, "whoami")
    assert code == exit_code and out["ok"] is False
    assert "secret-key" not in json.dumps(out)


def test_erase_requires_exact_confirmation_before_request(monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect", lambda _: pytest.fail("must not connect"))
    code, out, _ = invoke(capsys, "users", "erase", "someone")
    assert code == 2 and "ERASE ALL DATA" in out["error"]["message"]


def test_job_wait_and_download(monkeypatch, capsys, tmp_path):
    def handle(request):
        if request.url.path == "/v1/export":
            return httpx.Response(202, json={"job_id": "job1", "status": "queued"})
        if request.url.path.endswith("/download"):
            return httpx.Response(200, content=b'{"memories":[]}')
        return httpx.Response(200, json={"id": "job1", "status": "complete", "result": {}})

    mock_client(monkeypatch, handle)
    target = tmp_path / "download.json"
    code, out, _ = invoke(capsys, "export", "--wait", "1", "--output", str(target))
    assert code == 0 and target.read_text() == '{"memories":[]}'
    assert out["data"]["bytes"] > 0


def test_failed_download_does_not_replace_existing_file(tmp_path):
    target = tmp_path / "export.json"
    target.write_text("old")
    client = Client(
        "https://memory.example",
        transport=httpx.MockTransport(lambda _: httpx.Response(403, json={"detail": "no"})),
    )
    with pytest.raises(ClientError):
        client.request("GET", "/v1/jobs/id/download", output=target)
    assert target.read_text() == "old"


def test_agent_install_preserves_settings_and_is_idempotent(tmp_path):
    from memos_cli.agents import install

    home = tmp_path / "claude"
    home.mkdir()
    original = {
        "model": "unchanged",
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {"type": "command", "command": "my-hook"},
                        {"type": "command", "command": "python memkit_hooks.py capture"},
                    ]
                }
            ]
        },
    }
    (home / "settings.json").write_text(json.dumps(original))
    install(["claude"], home=home)
    first = (home / "settings.json").read_text()
    backups = list(home.glob("settings.json.before-memos-*"))
    install(["claude"], home=home)
    assert first == (home / "settings.json").read_text()
    assert list(home.glob("settings.json.before-memos-*")) == backups
    parsed = json.loads(first)
    assert parsed["model"] == "unchanged"
    commands = [h["command"] for entry in parsed["hooks"]["Stop"] for h in entry["hooks"]]
    assert "my-hook" in commands
    assert sum("memos_cli internal hook" in c for c in commands) == 1
    assert "UserPromptSubmit" in parsed["hooks"]


def test_hermes_installer_preserves_other_plugins(tmp_path):
    import yaml

    from memos_cli.agents import install

    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        "plugins:\n  unrelated:\n    enabled: true\n  memkit:\n    api_key_file: old-secret\n"
    )
    install(["hermes"], home=home)
    data = yaml.safe_load((home / "config.yaml").read_text())
    assert data["plugins"]["unrelated"]["enabled"] is True
    assert "api_key_file" not in data["plugins"]["memkit"]
    assert (home / "plugins/memkit/bridge.json").exists()


def test_capture_only_reads_delta_and_keeps_incomplete_line(tmp_path):
    from memos_cli.claude_hooks import events_from_delta

    transcript, cursor = tmp_path / "session.jsonl", tmp_path / "cursor"
    turn = {
        "type": "user",
        "uuid": "id1",
        "sessionId": "s",
        "promptSource": "typed",
        "message": {"content": "User prefers pnpm"},
    }
    full = json.dumps(turn).encode() + b"\n"
    transcript.write_bytes(full + b'{"type":')
    events, offset = events_from_delta(transcript, cursor, "work")
    assert len(events) == 1 and offset == len(full)
    cursor.write_text(str(offset))
    events, second = events_from_delta(transcript, cursor, "work")
    assert events == [] and second == offset
    assert events_from_delta(transcript, tmp_path / "missing", "work")[0][0]["external_id"] == "id1"


def test_hooks_fail_open_when_unconfigured(capsys):
    from memos_cli import claude_hooks

    assert claude_hooks._client() is None


def test_https_required_and_redirects_do_not_forward_key():
    with pytest.raises(ClientError):
        Client("http://public.example", "secret")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://other.example"})

    client = Client("https://memory.example", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(ClientError):
        client.get("/v1/auth/me")
    assert len(seen) == 1


def test_server_only_executes_ssh_on_client(monkeypatch):
    from memos_cli import server

    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok":true,"data":{"ready":true}}')

    monkeypatch.setattr(subprocess, "run", run)
    assert server.remote(
        {"host": "deploy@example", "directory": "/srv/memos"}, {"action": "start"}
    ) == {"ready": True}
    assert calls[0][0][0] == "ssh"
    assert json.loads(calls[0][1]["input"])["directory"] == "/srv/memos"
    with pytest.raises(ClientError):
        server.host_check("-oProxyCommand=evil")


def worker_module():
    path = Path(__file__).resolve().parents[1] / "src/memos_cli/assets/server_worker.py"
    spec = importlib.util.spec_from_file_location("remote_worker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remote_refuses_unmanaged_directory_before_docker(tmp_path, monkeypatch):
    worker = worker_module()
    (tmp_path / "compose.yml").write_text("external")
    monkeypatch.setattr(worker, "run", lambda *a, **k: pytest.fail("no Docker call expected"))
    with pytest.raises(RuntimeError, match="take over"):
        worker.perform({"action": "install", "directory": str(tmp_path)})


def test_remote_compose_persists_data_and_binds_loopback():
    worker = worker_module()
    compose = worker.compose_config("example/memos:0.1", 8077, True)
    assert compose["services"]["app"]["ports"] == ["127.0.0.1:8077:8077"]
    assert "ports" not in compose["services"]["postgres"]
    assert "ports" not in compose["services"]["qdrant"]
    assert "pgdata" in compose["volumes"]
    with pytest.raises(RuntimeError):
        worker.image_check("example/memos:latest")


def test_no_server_imports_in_fresh_process():
    root = Path(__file__).resolve().parents[1] / "src"
    source = "from memos_cli.cli import parser_tree; parser_tree(); import sys; assert not any(n in sys.modules for n in ('memkit','torch','sentence_transformers','psycopg','qdrant_client'))"
    result = subprocess.run(
        [sys.executable, "-c", source],
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_oversized_transcript_lines_do_not_stall_capture(tmp_path):
    from memos_cli.capture import MAX_DELTA_BYTES, events_from_delta

    transcript, cursor = tmp_path / "transcript", tmp_path / "cursor"
    turn = {"type": "user", "uuid": "real", "sessionId": "s", "message": {"content": "Use pnpm"}}
    transcript.write_bytes(
        b"x" * (MAX_DELTA_BYTES + 200) + b"\n" + json.dumps(turn).encode() + b"\n"
    )
    events, offset = events_from_delta(transcript, cursor, "work")
    assert not events and offset == MAX_DELTA_BYTES
    cursor.write_text(str(offset))
    events, offset = events_from_delta(transcript, cursor, "work")
    assert len(events) == 1 and events[0]["external_id"] == "real"
    assert offset == transcript.stat().st_size


def test_validation_errors_do_not_echo_password_inputs(monkeypatch, capsys):
    mock_client(
        monkeypatch,
        lambda _: httpx.Response(
            422,
            json={
                "detail": [
                    {"loc": ["body", "password"], "msg": "too short", "input": "do-not-print"}
                ]
            },
        ),
    )
    code, out, _ = invoke(
        capsys,
        "auth",
        "password",
        "--data",
        '{"current_password":"do-not-print","new_password":"new-password"}',
    )
    assert code == 2
    assert "do-not-print" not in json.dumps(out)


def test_named_setup_does_not_send_another_servers_key(monkeypatch, capsys):
    configured()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    code, out, _ = invoke(capsys, "setup", "--name", "second", "--url", "https://second.example")
    assert code == 2 and "--api-key-file" in out["error"]["message"]


def test_recall_default_can_be_disabled_per_repository(tmp_path):
    from memos_cli.claude_hooks import repo_settings

    assert repo_settings(tmp_path).recall is True
    (tmp_path / ".memkit.toml").write_text("[memkit]\nrecall=false\n")
    assert repo_settings(tmp_path).recall is False


def test_capture_cursor_only_advances_after_success(tmp_path, monkeypatch):
    from memos_cli import claude_hooks

    transcript = tmp_path / "transcript"
    transcript.write_text(
        json.dumps(
            {"type": "user", "uuid": "u", "sessionId": "s", "message": {"content": "Prefers pnpm"}}
        )
        + "\n"
    )
    monkeypatch.setattr(claude_hooks, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(claude_hooks, "entity_cache", lambda *args: [])
    calls = []

    class FakeClient:
        def post(self, *args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise ClientError("unavailable", exit_code=7)

    repo = claude_hooks.repo_settings(tmp_path)
    with pytest.raises(ClientError):
        claude_hooks._flush(FakeClient(), transcript, "s", repo, "work")
    assert not (tmp_path / "state/s.offset").exists()
    claude_hooks._flush(FakeClient(), transcript, "s", repo, "work")
    assert (tmp_path / "state/s.offset").read_text() == str(transcript.stat().st_size)
    assert calls[0][1]["events"][0]["external_id"] == calls[1][1]["events"][0]["external_id"]


def test_non_api_commands_are_discoverable(capsys):
    code, out, _ = invoke(capsys, "schema", "server", "upgrade")
    assert code == 0
    assert any("--image" in item["flags"] for item in out["data"]["arguments"])
    code, out, _ = invoke(capsys, "commands")
    assert code == 0
    assert any(item["command"] == "server backup restore" for item in out["data"]["local_commands"])


def managed_worker(tmp_path):
    worker = worker_module()
    metadata = {"image": "memos:old", "port": 8077, "version": 1}
    (tmp_path / ".memos-managed.json").write_text(json.dumps(metadata))
    (tmp_path / "compose.json").write_text(
        json.dumps(worker.compose_config("memos:old", 8077, False))
    )
    (tmp_path / "server.env").write_text("POSTGRES_PASSWORD=private\n")
    return worker


def test_failed_upgrade_restores_previous_image(tmp_path, monkeypatch):
    worker = managed_worker(tmp_path)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "run"]:
            return "1\n"
        if "backup" in argv and "create" in argv:
            return json.dumps({"id": "backup-before-upgrade"})
        if "up" in argv:
            image = json.loads((tmp_path / "compose.json").read_text())["services"]["app"]["image"]
            if image == "memos:new":
                raise RuntimeError("new container fails health check")
        return ""

    monkeypatch.setattr(worker, "run", run)
    with pytest.raises(RuntimeError, match="previous image restored"):
        worker.perform({"action": "upgrade", "directory": str(tmp_path), "image": "memos:new"})
    assert (
        json.loads((tmp_path / "compose.json").read_text())["services"]["app"]["image"]
        == "memos:old"
    )
    assert len([c for c in calls if "up" in c]) == 2


def test_schema_changing_upgrade_never_restarts_app(tmp_path, monkeypatch):
    worker = managed_worker(tmp_path)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return "2\n" if "memos:new" in argv else "1\n"

    monkeypatch.setattr(worker, "run", run)
    with pytest.raises(RuntimeError, match="migration"):
        worker.perform({"action": "upgrade", "directory": str(tmp_path), "image": "memos:new"})
    assert not any("up" in call or "stop" in call for call in calls)


def test_restore_stops_app_and_refuses_other_database_writers(tmp_path, monkeypatch):
    import hashlib

    worker = managed_worker(tmp_path)
    backup = tmp_path / "backups/one.dump"
    backup.parent.mkdir()
    backup.write_bytes(b"verified fixture")
    artifact = {
        "id": "one",
        "path": "/backups/one.dump",
        "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
    }
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "backup" in argv and "list" in argv:
            return json.dumps([artifact])
        if "backup" in argv and "create" in argv:
            return json.dumps({"id": "recovery"})
        if "psql" in argv:
            return "1\n"
        return "{}"

    monkeypatch.setattr(worker, "run", run)
    with pytest.raises(RuntimeError, match="Other database clients"):
        worker.perform(
            {
                "action": "backup-restore",
                "directory": str(tmp_path),
                "artifact_id": "one",
                "confirm": "RESTORE",
            }
        )
    assert any("stop" in call for call in calls)
    assert not any("pg_restore" in " ".join(call) for call in calls)


def test_timeout_has_stable_machine_error(monkeypatch, capsys):
    def timeout(request):
        raise httpx.ReadTimeout("simulated")

    mock_client(monkeypatch, timeout)
    code, out, _ = invoke(capsys, "search", "decision")
    assert code == 8 and out["error"]["code"] == "timeout"


def test_hermes_bridge_uses_cli_connection_and_transport(tmp_path, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from memos_cli.agents import install

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(
                (
                    self.path,
                    self.headers.get("X-API-Key"),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"memories":[{"id":"one","text":"Uses pnpm"}]}')

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        config.save(
            {
                "default": "hosted",
                "connections": {
                    "hosted": {
                        "url": f"http://127.0.0.1:{http.server_port}",
                        "key": "test-identity",
                    }
                },
            }
        )
        home = tmp_path / "hermes"
        install(["hermes"], home=home)
        monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
        spec = importlib.util.spec_from_file_location(
            "hermes_bridge_client", home / "plugins/memkit/client.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        client = module.Client(*module.resolve_config(), timeout=3)
        assert client.search("package manager")[0]["text"] == "Uses pnpm"
        assert seen[0][0] == "/v1/memories/search" and seen[0][1] == "test-identity"
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def test_installed_hook_fails_open_with_bad_configuration(tmp_path):
    config.config_dir().mkdir()
    (config.config_dir() / "connections.json").write_text("broken json")
    source = Path(__file__).resolve().parents[1] / "src"
    result = subprocess.run(
        [sys.executable, "-m", "memos_cli", "internal", "hook", "session-start"],
        input='{"session_id":"s"}',
        env={**os.environ, "PYTHONPATH": str(source)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and result.stdout == ""
    assert "unavailable" in result.stderr


def test_text_command_discovery_is_compact(capsys):
    assert cli.main(["commands", "--text"]) == 0
    output = capsys.readouterr().out
    assert "Everyday:" in output and "server:" in output
    assert "properties" not in output and len(output.splitlines()) < 30


def test_backup_catalog_survives_database_failure(tmp_path, monkeypatch):
    worker = managed_worker(tmp_path)
    artifact = {"id": "recovery", "path": "/backups/recovery.dump", "sha256": "digest"}
    (tmp_path / "backup-catalog.json").write_text(json.dumps({"recovery": artifact}))

    def unavailable(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(worker, "run", unavailable)
    assert worker.perform({"action": "backup-list", "directory": str(tmp_path)}) == [artifact]


@pytest.mark.parametrize("target", ["claude", "hermes", "codex", "custom"])
def test_common_guide_installs_with_http_fallback(tmp_path, target):
    from importlib.resources import files

    from memos_cli.agents import install

    home = tmp_path / target
    if target == "custom":
        install([], skills_dir=str(home))
        directory = home / "mem-os"
    else:
        install([target], home=str(home))
        directory = home / "skills/mem-os"
    for name in ("SKILL.md", "HTTP.md"):
        assert (directory / name).read_text() == files("memos_cli").joinpath(
            f"assets/{name}"
        ).read_text()


def test_common_guide_commands_parse_against_the_installed_cli(monkeypatch, capsys):
    import re
    import shlex
    from importlib.resources import files

    guide = files("memos_cli").joinpath("assets/SKILL.md").read_text()
    commands = re.findall(r"`memos ([^`]+)`", guide)
    assert len(commands) >= 15
    monkeypatch.setattr(cli, "dispatch", lambda args, options: {"parsed": True})
    for command in commands:
        argv = ["3" if token == "N" else token for token in shlex.split(command)]
        result = cli.main(argv)
        assert result == 0, (command, capsys.readouterr())
