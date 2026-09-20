"""Execute named API operations and bounded pagination."""

import json
import math
import time
from pathlib import Path
from urllib.parse import quote

from . import config
from .arguments import read_value
from .client import object_response, protocol_error
from .errors import ClientError


def execute(args, options, *, connect, public_connect):
    op = args.operation
    values = vars(args)
    body = json.loads(read_value(args.data)) if args.data else {}
    if not isinstance(body, dict):
        raise ClientError("--data must be a JSON object")
    properties = op["body"].get("properties", {})
    path, params = op["path"], {}
    for parameter in op["parameters"]:
        name = parameter["name"]
        value = values.get(name)
        if parameter["in"] == "path":
            if value is None:
                raise ClientError(f"{name} is required")
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        elif name in values:
            params[name] = value
    used = {p["name"] for p in op["parameters"]}
    for name in properties:
        key = "body_" + name if name in used else name
        if key in values:
            body[name] = values[key]
    if op["command"] == "remember":
        body.setdefault("kind", "fact")
        body.setdefault("source_role", "manual")
    if op["path"] == "/v1/memories" and op["method"] == "POST":
        scope = config.repository().get("entity")
        if scope:
            body.setdefault("scope", scope)
    if op["command"] in {"profile", "profiles render"}:
        body.setdefault("budget_tokens", 600)
        body.setdefault("workspace", Path.cwd().name)
    if op["path"].endswith("/erase") and body.get("confirm") != "ERASE ALL DATA":
        raise ClientError('Erasure requires --confirm "ERASE ALL DATA".')
    if not math.isfinite(args.wait) or args.wait < 0 or args.wait > 3600:
        raise ClientError("--wait must be between 0 and 3600 seconds")
    if op["command"] == "jobs download" and not args.output:
        raise ClientError("Use --output FILE for an export download.")
    if op["path"] in {"/healthz", "/readyz", "/v1/auth/login"}:
        client = public_connect(options)
    else:
        client = connect(options)
    try:
        if (
            op["method"] == "PATCH"
            and "expected_revision" in properties
            and "expected_revision" not in body
        ):
            current = client.get(path)
            memory = object_response(current.get("memory", current))
            if type(memory.get("revision")) is not int:
                raise protocol_error()
            body["expected_revision"] = memory["revision"]
        missing = [name for name in op["body"].get("required", []) if name not in body]
        if missing:
            raise ClientError(
                "Required fields: " + ", ".join("--" + name.replace("_", "-") for name in missing)
            )
        download = args.output if op["command"] == "jobs download" else None
        deadline = time.monotonic() + (args.wait or 60) if getattr(args, "all", False) else None
        result = client.request(
            op["method"],
            path,
            body if properties or args.data else None,
            params,
            output=download,
            timeout=min(client.timeout, args.wait or 60) if deadline is not None else None,
        )
        if getattr(args, "all", False):

            def remaining():
                seconds = deadline - time.monotonic()
                if seconds <= 0:
                    raise ClientError(
                        "Pagination timed out; use --limit and --offset or increase --wait.",
                        code="timeout",
                        exit_code=8,
                    )
                return min(client.timeout, seconds)

            remaining()
            key = next(
                (k for k in ("items", "memories", "messages") if isinstance(result.get(k), list)),
                None,
            )
            if key is None:
                raise protocol_error()
            limit = params.get("limit") or next(
                (p["schema"].get("default", 50) for p in op["parameters"] if p["name"] == "limit"),
                50,
            )
            page = list(result[key])
            while len(page) >= limit:
                params["offset"] = params.get("offset", 0) + len(page)
                next_result = client.request(
                    op["method"],
                    path,
                    params=params,
                    timeout=remaining(),
                )
                remaining()
                page = next_result.get(key)
                if not isinstance(page, list):
                    raise protocol_error()
                result[key].extend(page)
        if args.wait and (result.get("job_id") or op["command"] == "jobs get"):
            result = client.wait(result.get("job_id") or args.job_id, args.wait)
        if args.output and not download:
            if op["command"] == "export":
                job_id = (
                    result.get("job_id")
                    or result.get("id")
                    or object_response(result.get("job", {})).get("id")
                )
                if not isinstance(job_id, str) or not job_id:
                    raise protocol_error()
                if not args.wait:
                    client.wait(job_id, 60)
                return client.request("GET", f"/v1/jobs/{job_id}/download", output=args.output)
            config.private_write(
                Path(args.output).expanduser(),
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            )
            return {"path": str(Path(args.output).expanduser().resolve())}
        return result
    finally:
        client.close()
