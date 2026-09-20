"""Identity HTTP endpoints."""

from __future__ import annotations

import logging
from typing import Annotated, Any

import psycopg
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)

from .. import (
    auth,
    entities,
    jobs,
    users,
)
from .. import (
    principal as principal_module,
)
from ..config import Settings, get_settings
from ..db import iso
from ..http import (
    SESSION_COOKIE,
    _memory_summary,
    _wake_worker,
    get_conn,
    get_principal,
    require_admin,
)
from ..principal import Principal
from ..schemas import (
    AliasIn,
    ApiKeyIn,
    ApiKeysOut,
    EntitiesOut,
    EntityCreatedOut,
    EntityIn,
    EntityPatch,
    EntityProfileOut,
    EntityView,
    EraseIn,
    FeedbackOut,
    FlexibleOut,
    JobQueuedOut,
    KeyCreatedOut,
    LoginIn,
    MemberIn,
    PasswordChangeIn,
    PrincipalView,
    ResolveIn,
    SessionOut,
    UserIn,
    UserPatch,
    UsersOut,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _scope_summaries(conn: psycopg.Connection, principal: Principal) -> list[dict[str, Any]]:
    rows = entities.visible_to(conn, principal.user_id)
    return [
        {
            "id": str(row["id"]),
            "slug": row["slug"],
            "kind": row["kind"],
            "name": row["name"],
            "writable": str(row["id"]) in principal.writable_scope_ids,
        }
        for row in rows
    ]


@router.post("/v1/auth/login", response_model=SessionOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Exchange a password for a session cookie.

    Failures are counted per handle and per address and answered identically,
    so the endpoint cannot be used to discover which handles exist.
    """
    limiter: auth.RateLimiter = request.app.state.login_limiter
    address = request.client.host if request.client else "unknown"
    keys = (f"handle:{body.handle.casefold()}", f"ip:{address}")
    if not limiter.check(*keys):
        raise HTTPException(429, "too many attempts; wait a minute")
    user = users.by_handle(conn, body.handle)
    if user is None or user["disabled_at"] is not None:
        limiter.record(*keys)
        raise HTTPException(401, "invalid credentials")
    if not auth.verify_password(str(user["password_hash"]), body.password):
        limiter.record(*keys)
        raise HTTPException(401, "invalid credentials")
    limiter.reset(*keys)
    with conn.transaction():
        if auth.needs_rehash(str(user["password_hash"])):
            users.set_password(conn, user_id=str(user["id"]), password=body.password)
        token = auth.start_session(
            conn,
            user_id=str(user["id"]),
            ttl_days=settings.session_ttl_days,
            ip=address,
            user_agent=request.headers.get("user-agent"),
        )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_days * 86_400,
        path="/",
    )
    caller = principal_module.load(conn, str(user["id"]), auth_kind="session")
    return {"user": principal_module.describe(caller, _scope_summaries(conn, caller))}


@router.post("/v1/auth/logout")
def logout(
    response: Response,
    memkit_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedbackOut:
    if memkit_session:
        with conn.transaction():
            auth.revoke_session(conn, memkit_session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"recorded": True}


@router.get("/v1/auth/me")
def whoami(
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> PrincipalView:
    return principal_module.describe(principal, _scope_summaries(conn, principal))


@router.post("/v1/auth/password")
def change_password(
    body: PasswordChangeIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    memkit_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> FeedbackOut:
    """Change a password and sign the user out everywhere else.

    Other sessions are revoked because the usual reason to change a password is
    that somebody else may have had it.
    """
    user = users.by_id(conn, principal.user_id)
    if user is None or not auth.verify_password(str(user["password_hash"]), body.current_password):
        raise HTTPException(403, "current password does not match")
    with conn.transaction():
        users.set_password(conn, user_id=principal.user_id, password=body.new_password)
        auth.revoke_all_sessions(conn, user_id=principal.user_id, keep=memkit_session)
    return {"recorded": True}


@router.get("/v1/api-keys")
def list_api_keys(
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ApiKeysOut:
    rows = conn.execute(
        """SELECT id,name,key_prefix,created_at,last_used_at,revoked_at
             FROM api_keys WHERE user_id=%s ORDER BY created_at DESC""",
        (principal.user_id,),
    ).fetchall()
    return {
        "items": [
            {
                "id": str(row["id"]),
                "name": row["name"],
                "key_prefix": row["key_prefix"],
                "created_at": iso(row["created_at"]),
                "last_used_at": iso(row["last_used_at"]),
                "revoked_at": iso(row["revoked_at"]),
            }
            for row in rows
        ]
    }


@router.post("/v1/api-keys", status_code=201)
def create_api_key(
    body: ApiKeyIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> KeyCreatedOut:
    """Mint a key. The secret is returned once and never stored in the clear."""
    target = principal.user_id
    if body.user_id and body.user_id != principal.user_id:
        if not principal.is_admin:
            raise HTTPException(403, "only an administrator may create keys for another user")
        if users.by_id(conn, body.user_id) is None:
            raise HTTPException(404, "unknown user")
        target = body.user_id
    with conn.transaction():
        minted = auth.mint_api_key(conn, user_id=target, name=body.name)
    return {
        "id": minted.id,
        "name": body.name,
        "key_prefix": minted.prefix,
        "secret": minted.token,
    }


@router.delete("/v1/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedbackOut:
    with conn.transaction():
        revoked = auth.revoke_api_key(
            conn, key_id=key_id, user_id=None if principal.is_admin else principal.user_id
        )
    if not revoked:
        raise HTTPException(404, "unknown or already revoked key")
    return {"recorded": True}


def _user_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": str(data["id"]),
        "handle": data["handle"],
        "display_name": data["display_name"],
        "email": data.get("email"),
        "role": data["role"],
        "created_at": iso(data.get("created_at")),
        "disabled_at": iso(data.get("disabled_at")),
        "own_entity_id": str(data["own_entity_id"]) if data.get("own_entity_id") else None,
        "key_last_used_at": iso(data.get("key_last_used_at")),
    }


@router.get("/v1/users")
def list_users(
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> UsersOut:
    """Everyone on the team.

    Not admin-only: a team memory system is unusable if you cannot see who your
    teammates are, and a fact can name any of them as its subject. Only
    identity is exposed here, never credentials.
    """
    return {"items": [_user_row(row) for row in users.listing(conn)]}


@router.post("/v1/users", status_code=201)
def create_user(
    body: UserIn,
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    try:
        with conn.transaction():
            row = users.create(
                conn,
                handle=body.handle,
                display_name=body.display_name,
                password=body.password,
                role=body.role,
                email=body.email,
            )
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, "handle or email is already taken") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": str(row["id"]), "handle": row["handle"], "role": row["role"]}


@router.patch("/v1/users/{user_id}")
def patch_user(
    user_id: str,
    body: UserPatch,
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    """Change a role or disable an account.

    The last enabled administrator cannot be demoted or disabled: an instance
    with no administrator cannot create users, keys, or entities again.
    """
    target = users.by_id(conn, user_id)
    if target is None:
        raise HTTPException(404, "unknown user")
    losing_admin = (body.role == "member" and target["role"] == "admin") or bool(body.disabled)
    if (
        losing_admin
        and target["role"] == "admin"
        and users.count_admins(conn, excluding=user_id) == 0
    ):
        raise HTTPException(409, "the last administrator cannot be demoted or disabled")
    with conn.transaction():
        row = users.update(
            conn,
            user_id=user_id,
            display_name=body.display_name,
            role=body.role,
            disabled=body.disabled,
        )
    if row is None:
        raise HTTPException(404, "unknown user")
    return {"id": str(row["id"]), "role": row["role"], "disabled_at": iso(row["disabled_at"])}


def _entity_row(conn: psycopg.Connection, row: Any, principal: Principal) -> dict[str, Any]:
    entity_id = str(row["id"])
    return {
        "id": entity_id,
        "kind": row["kind"],
        "name": row["name"],
        "slug": row["slug"],
        "description": row["description"],
        "visibility": row["visibility"],
        "aliases": entities.aliases_of(conn, entity_id),
        "writable": entity_id in principal.writable_scope_ids,
        "created_at": iso(row["created_at"]),
        "archived_at": iso(row["archived_at"]),
    }


def _load_entity(conn: psycopg.Connection, principal: Principal, slug: str) -> Any:
    row = entities.by_slug(conn, slug)
    if row is None:
        raise HTTPException(404, "unknown entity")
    entity_id = str(row["id"])
    # A teammate's user entity is visible as a subject even though its scope is
    # not readable, so identity lookups work without exposing private memory.
    if entity_id not in principal.allowed_scope_ids and row["kind"] != "user":
        raise HTTPException(403, "entity is not accessible")
    return row


@router.get("/v1/entities")
def list_entities(
    kind: str | None = None,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntitiesOut:
    rows = entities.visible_to(conn, principal.user_id)
    if kind:
        rows = [row for row in rows if row["kind"] == kind]
    people = [] if kind and kind != "user" else entities.teammates(conn, principal.user_id)
    seen = {str(row["id"]) for row in rows}
    rows = rows + [row for row in people if str(row["id"]) not in seen]
    return {"items": [_entity_row(conn, row, principal) for row in rows]}


@router.post("/v1/entities", status_code=201)
def create_entity(
    body: EntityIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityCreatedOut:
    try:
        with conn.transaction():
            row = entities.create(
                conn,
                kind=body.kind,
                name=body.name,
                slug=body.slug,
                description=body.description,
                visibility=body.visibility,
                created_by=principal.user_id,
                aliases=list(body.aliases),
            )
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, "slug is already taken") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": str(row["id"]), "slug": row["slug"], "kind": row["kind"]}


@router.get("/v1/entities/{slug}")
def get_entity(
    slug: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityView:
    row = _load_entity(conn, principal, slug)
    payload = _entity_row(conn, row, principal)
    payload["members"] = [
        {
            "user_id": str(member["user_id"]),
            "handle": member["handle"],
            "display_name": member["display_name"],
            "role": member["role"],
        }
        for member in entities.members(conn, str(row["id"]))
    ]
    return payload


@router.patch("/v1/entities/{slug}")
def patch_entity(
    slug: str,
    body: EntityPatch,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityView:
    row = _load_entity(conn, principal, slug)
    entity_id = str(row["id"])
    if not principal.may_write(entity_id) and not principal.is_admin:
        raise HTTPException(403, "entity is read-only for this user")
    with conn.transaction():
        updated = conn.execute(
            """UPDATE entities SET
                  name = COALESCE(%s, name),
                  description = COALESCE(%s, description),
                  visibility = COALESCE(%s, visibility)
                WHERE id=%s RETURNING *""",
            (body.name, body.description, body.visibility, entity_id),
        ).fetchone()
    return _entity_row(conn, updated, principal)


@router.post("/v1/entities/{slug}/archive")
def archive_entity(
    slug: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    """Hide an entity without deleting its memory.

    Archiving rather than deleting because the memories in that scope cite real
    conversations; a project that ended is still a record of what was decided.
    """
    row = _load_entity(conn, principal, slug)
    if row["kind"] in entities.SYSTEM_KINDS:
        raise HTTPException(409, "a user or team entity cannot be archived")
    if not principal.may_write(str(row["id"])) and not principal.is_admin:
        raise HTTPException(403, "entity is read-only for this user")
    with conn.transaction():
        conn.execute(
            "UPDATE entities SET archived_at=COALESCE(archived_at, now()) WHERE id=%s",
            (str(row["id"]),),
        )
    return {"id": str(row["id"]), "archived": True}


@router.post("/v1/entities/{slug}/aliases", status_code=201)
def add_entity_alias(
    slug: str,
    body: AliasIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    row = _load_entity(conn, principal, slug)
    if not principal.may_write(str(row["id"])) and not principal.is_admin:
        raise HTTPException(403, "entity is read-only for this user")
    with conn.transaction():
        added = entities.add_aliases(conn, entity_id=str(row["id"]), aliases=[body.alias])
    if not added:
        raise HTTPException(409, "alias is already claimed by another entity")
    return {"id": str(row["id"]), "aliases": entities.aliases_of(conn, str(row["id"]))}


@router.delete("/v1/entities/{slug}/aliases/{alias}")
def remove_entity_alias(
    slug: str,
    alias: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedbackOut:
    row = _load_entity(conn, principal, slug)
    if not principal.may_write(str(row["id"])) and not principal.is_admin:
        raise HTTPException(403, "entity is read-only for this user")
    with conn.transaction():
        removed = entities.remove_alias(conn, entity_id=str(row["id"]), alias=alias)
    if not removed:
        raise HTTPException(404, "unknown alias")
    return {"recorded": True}


@router.put("/v1/entities/{slug}/members/{user_id}")
def put_member(
    slug: str,
    user_id: str,
    body: MemberIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    row = _load_entity(conn, principal, slug)
    if row["kind"] in entities.SYSTEM_KINDS:
        raise HTTPException(409, "membership of a user or team entity is managed by the system")
    members = {str(m["user_id"]): m["role"] for m in entities.members(conn, str(row["id"]))}
    if members.get(principal.user_id) != "owner" and not principal.is_admin:
        raise HTTPException(403, "only an entity owner or an administrator may change members")
    if users.by_id(conn, user_id) is None:
        raise HTTPException(404, "unknown user")
    with conn.transaction():
        entities.set_member(conn, entity_id=str(row["id"]), user_id=user_id, role=body.role)
    return {"entity_id": str(row["id"]), "user_id": user_id, "role": body.role}


@router.delete("/v1/entities/{slug}/members/{user_id}")
def delete_member(
    slug: str,
    user_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedbackOut:
    row = _load_entity(conn, principal, slug)
    if row["kind"] in entities.SYSTEM_KINDS:
        raise HTTPException(409, "membership of a user or team entity is managed by the system")
    members = {str(m["user_id"]): m["role"] for m in entities.members(conn, str(row["id"]))}
    if members.get(principal.user_id) != "owner" and not principal.is_admin:
        raise HTTPException(403, "only an entity owner or an administrator may change members")
    with conn.transaction():
        removed = entities.remove_member(conn, entity_id=str(row["id"]), user_id=user_id)
    if not removed:
        raise HTTPException(404, "user is not a member")
    return {"recorded": True}


@router.post("/v1/entities/resolve")
def resolve_entity(
    body: ResolveIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    """Turn a name from conversation into an entity, or nothing.

    Exact alias match only. A near match would attach a claim to the wrong
    person, which is worse than reporting that the name is unknown.
    """
    row = entities.resolve_alias(conn, body.name)
    if row is None:
        return {"entity": None}
    return {"entity": _entity_row(conn, row, principal)}


@router.get("/v1/entities/{slug}/profile")
def entity_profile(
    slug: str,
    budget_tokens: int = Query(800, ge=1, le=20_000),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityProfileOut:
    """What is known about this entity, and what lives in its scope.

    Two different questions, answered together because a page about a person
    needs both: facts the team recorded about them, and facts they recorded
    themselves in a scope the caller shares.
    """
    row = _load_entity(conn, principal, slug)
    entity_id = str(row["id"])
    about = conn.execute(
        """SELECT m.*, sc.name AS scope_name FROM memories m
             JOIN entities sc ON sc.id = m.scope_id
            WHERE m.subject_id=%s AND m.status='active' AND m.scope_id = ANY(%s)
            ORDER BY m.importance DESC, m.updated_at DESC LIMIT 100""",
        (entity_id, principal.scopes()),
    ).fetchall()
    in_scope = (
        conn.execute(
            """SELECT m.*, sc.name AS scope_name FROM memories m
                 JOIN entities sc ON sc.id = m.scope_id
                WHERE m.scope_id=%s AND m.status='active' AND m.subject_id IS NULL
                ORDER BY m.importance DESC, m.updated_at DESC LIMIT 100""",
            (entity_id,),
        ).fetchall()
        if entity_id in principal.allowed_scope_ids
        else []
    )
    return {
        "entity": _entity_row(conn, row, principal),
        "about": [_memory_summary(item) for item in about],
        "in_scope": [_memory_summary(item) for item in in_scope],
        "budget_tokens": budget_tokens,
    }


@router.post("/v1/users/{user_id}/erase", status_code=202)
def erase_user_data(
    request: Request,
    user_id: str,
    body: EraseIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    """Erase one user's private data.

    A user may erase themselves; only an administrator may erase somebody else.
    Memories they authored in shared scopes are the team's record and are not
    removed -- the job refuses rather than deleting them, and says how many.
    """
    if user_id != principal.user_id and not principal.is_admin:
        raise HTTPException(403, "only an administrator may erase another user")
    own = entities.own_entity(conn, user_id)
    if own is None:
        raise HTTPException(404, "unknown user")
    with conn.transaction():
        job_id = jobs.create(
            conn,
            kind="erase",
            input_data={"user_id": user_id, "private_scope_id": str(own["id"])},
            user_id=principal.user_id,
        )
    _wake_worker(request)
    return {"job_id": job_id, "status": "queued"}
