"""Explicit, stable command names with OpenAPI-derived arguments."""

import json
from importlib.resources import files

ROUTES = {
    "health": ("GET", "/healthz"),
    "ready": ("GET", "/readyz"),
    "auth login": ("POST", "/v1/auth/login"),
    "auth logout": ("POST", "/v1/auth/logout"),
    "auth me": ("GET", "/v1/auth/me"),
    "auth password": ("POST", "/v1/auth/password"),
    "keys list": ("GET", "/v1/api-keys"),
    "keys create": ("POST", "/v1/api-keys"),
    "keys revoke": ("DELETE", "/v1/api-keys/{key_id}"),
    "users list": ("GET", "/v1/users"),
    "users create": ("POST", "/v1/users"),
    "users update": ("PATCH", "/v1/users/{user_id}"),
    "users erase": ("POST", "/v1/users/{user_id}/erase"),
    "entities list": ("GET", "/v1/entities"),
    "entities create": ("POST", "/v1/entities"),
    "entities resolve": ("POST", "/v1/entities/resolve"),
    "entities get": ("GET", "/v1/entities/{slug}"),
    "entities update": ("PATCH", "/v1/entities/{slug}"),
    "entities archive": ("POST", "/v1/entities/{slug}/archive"),
    "entities profile": ("GET", "/v1/entities/{slug}/profile"),
    "entities aliases add": ("POST", "/v1/entities/{slug}/aliases"),
    "entities aliases remove": ("DELETE", "/v1/entities/{slug}/aliases/{alias}"),
    "entities members set": ("PUT", "/v1/entities/{slug}/members/{user_id}"),
    "entities members remove": ("DELETE", "/v1/entities/{slug}/members/{user_id}"),
    "evidence add": ("POST", "/v1/evidence/events"),
    "evidence batch": ("POST", "/v1/evidence/events:batch"),
    "sessions close": ("POST", "/v1/sessions/{session_id}/close"),
    "sessions list": ("GET", "/v1/admin/sessions"),
    "sessions messages": ("GET", "/v1/admin/sessions/{session_id}/messages"),
    "sessions memories": ("GET", "/v1/admin/sessions/{session_id}/memories"),
    "memories list": ("GET", "/v1/memories"),
    "memories create": ("POST", "/v1/memories"),
    "memories search": ("POST", "/v1/memories/search"),
    "memories get": ("GET", "/v1/memories/{memory_id}"),
    "memories update": ("PATCH", "/v1/memories/{memory_id}"),
    "memories archive": ("DELETE", "/v1/memories/{memory_id}"),
    "memories restore": ("POST", "/v1/memories/{memory_id}/restore"),
    "memories review": ("POST", "/v1/memories/{memory_id}/review"),
    "memories history": ("GET", "/v1/memories/{memory_id}/history"),
    "memories sources": ("GET", "/v1/memories/{memory_id}/sources"),
    "review list": ("GET", "/v1/review"),
    "attention resolve": ("POST", "/v1/attention/{item_id}/resolve"),
    "profiles render": ("POST", "/v1/profiles/render"),
    "retrieval list": ("GET", "/v1/retrieval-runs"),
    "retrieval feedback": ("POST", "/v1/retrieval-runs/{retrieval_id}/feedback"),
    "retrieval legacy-feedback": ("POST", "/v1/retrieval-feedback"),
    "policies list": ("GET", "/v1/policies"),
    "policies create": ("POST", "/v1/policies"),
    "export": ("POST", "/v1/export"),
    "jobs list": ("GET", "/v1/jobs"),
    "jobs get": ("GET", "/v1/jobs/{job_id}"),
    "jobs cancel": ("POST", "/v1/jobs/{job_id}/cancel"),
    "jobs download": ("GET", "/v1/jobs/{job_id}/download"),
    "admin health": ("GET", "/v1/admin/health"),
    "admin metrics": ("GET", "/v1/admin/metrics"),
    "admin backups": ("GET", "/v1/admin/backups"),
    "admin reindex": ("POST", "/v1/admin/reindex"),
    "admin consolidate": ("POST", "/v1/admin/consolidate"),
    "admin reextract": ("POST", "/v1/admin/reextract"),
    "admin judge-runs list": ("GET", "/v1/admin/judge-runs"),
    "admin judge-runs get": ("GET", "/v1/admin/judge-runs/{run_id}"),
    **{
        f"admin stats {name}": ("GET", f"/v1/admin/stats/{name}")
        for name in ("entities", "memories", "pipeline", "retrieval", "review", "users")
    },
}

ALIASES = {
    "remember": "memories create",
    "search": "memories search",
    "profile": "profiles render",
    "forget": "memories archive",
    "whoami": "auth me",
}


def spec():
    return json.loads(files("memos_cli").joinpath("openapi.json").read_text())


def deref(schema, document):
    if "$ref" in schema:
        return deref(document["components"]["schemas"][schema["$ref"].split("/")[-1]], document)
    if "anyOf" in schema:
        choices = [item for item in schema["anyOf"] if item.get("type") != "null"]
        if len(choices) == 1:
            return deref(choices[0], document)
    return schema


def operation(command, document=None):
    document = document or spec()
    canonical = ALIASES.get(command, command)
    method, path = ROUTES[canonical]
    op = document["paths"][path][method.lower()]
    body = (
        op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
    )
    return {
        "command": command,
        "method": method,
        "path": path,
        "description": op.get("description") or op.get("summary", ""),
        "parameters": [p for p in op.get("parameters", []) if p["in"] in {"path", "query"}],
        "body": deref(body, document),
    }


def simple_type(schema):
    for candidate in schema.get("anyOf", [schema]):
        if candidate.get("type") != "null":
            return candidate.get("type", "object")
    return "string"
