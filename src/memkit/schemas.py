"""HTTP request and response contracts; arbitrary memory context stays JSON."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, NotRequired, TypedDict
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from . import (
    auth,
)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
Kind = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Slug = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
# An event date at the precision the speaker gave; see temporal.py.
EventDate = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")
]
Password = Annotated[str, StringConstraints(min_length=12, max_length=200)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class LoginIn(StrictModel):
    handle: Identifier
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class PasswordChangeIn(StrictModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    new_password: Password


class UserIn(StrictModel):
    handle: Identifier
    display_name: ShortText
    password: Password
    role: Literal["admin", "member"] = "member"
    email: Identifier | None = None


class UserPatch(StrictModel):
    display_name: ShortText | None = None
    role: Literal["admin", "member"] | None = None
    disabled: bool | None = None


class ApiKeyIn(StrictModel):
    name: ShortText
    user_id: Identifier | None = None


class EntityIn(StrictModel):
    kind: Literal["project", "product", "company", "person", "custom"]
    name: ShortText
    slug: Slug | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] = ""
    visibility: Literal["members", "team"] = "members"
    aliases: list[ShortText] = Field(default_factory=list, max_length=20)


class EntityPatch(StrictModel):
    name: ShortText | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    visibility: Literal["members", "team"] | None = None


class AliasIn(StrictModel):
    alias: ShortText


class MemberIn(StrictModel):
    role: Literal["owner", "member", "viewer"] = "member"


class ResolveIn(StrictModel):
    name: ShortText


class MessageIn(StrictModel):
    session_id: Identifier
    agent_id: Identifier = "chat"
    role: Literal["user", "assistant", "tool"]
    content: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000)
    ]
    external_source: Identifier | None = None
    external_id: Identifier | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    # Where facts from this conversation belong. A slug, `team`, `private`, or
    # omitted for private. Fixed when the session is created.
    scope: Slug | None = None
    created_at: AwareDatetime | None = None


class MessageOut(StrictModel):
    message_id: int
    indexed: bool
    index_status: str
    index_job_id: str | None = None
    extraction_job_id: str | None = None
    deduplicated: bool = False
    redacted: bool = False


class EvidenceBatchIn(StrictModel):
    events: Annotated[list[MessageIn], Field(min_length=1, max_length=100)]


class MemoryIn(StrictModel):
    text: ShortText
    kind: Kind
    context: dict[str, Any] = Field(default_factory=dict)
    tags: list[Kind] = Field(default_factory=list, max_length=20)
    agent_id: Identifier | None = None
    importance: float = Field(default=0.6, ge=0, le=1)
    confidence: float = Field(default=0.9, ge=0, le=1)
    valid_until: AwareDatetime | None = None
    source_role: Literal["user", "assistant", "agent", "tool", "manual"]
    scope: Slug | None = None
    subject: Slug | None = None
    # When the described thing happened: YYYY, YYYY-MM or YYYY-MM-DD.
    event_dates: list[EventDate] = Field(default_factory=list, max_length=8)
    # An enduring identity trait every profile should carry.
    is_static: bool = False
    # When the claim was said, for a backfill; defaults to now.
    document_date: AwareDatetime | None = None


class MemoryPatch(StrictModel):
    expected_revision: int = Field(ge=1)
    text: ShortText | None = None
    kind: Kind | None = None
    context: dict[str, Any] | None = None
    tags: list[Kind] | None = Field(default=None, max_length=20)
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    valid_until: AwareDatetime | None = None
    clear_valid_until: bool = False
    subject: Slug | None = None
    clear_subject: bool = False
    scope: Slug | None = None
    # Moving a fact between scopes changes who can read it, so it must be said
    # out loud rather than inferred from a field appearing in a patch.
    move_scope: bool = False
    move_context: bool = False
    event_dates: list[EventDate] | None = Field(default=None, max_length=8)
    is_static: bool | None = None


class ReviewIn(StrictModel):
    decision: Literal["confirm", "decline", "undo"]
    expected_revision: int | None = Field(default=None, ge=1)


class AttentionResolveIn(StrictModel):
    action: Literal["link_entity", "dismiss"]
    entity: Slug | None = None


class SearchIn(StrictModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8192)]
    filter: dict[str, Any] | None = None
    kinds: list[Kind] | None = None
    # Narrow the search to particular scopes. Omitted means every scope the
    # caller can read; naming one they cannot is a 403, not an empty result.
    scopes: list[Slug] | None = None
    subject: Slug | None = None
    # v2 adds time, reinforcement and inference to v1's fusion; "neutral-v1"
    # still names the previous ranking exactly (decisions/0077).
    policy_id: str = "core-retrieval-v2"
    include_untrusted: bool = False
    include_raw: bool = False
    include_sources: bool = False
    # Characters of the cited message around each source span -- the chunk the
    # claim came from. 0 returns the verified span alone, as before.
    source_context_chars: int = Field(default=0, ge=0, le=4000)
    # The claims each result replaced, with the dates they held.
    include_history: bool = False
    # Claims linked by extends/derives edges.
    include_related: bool = False
    # When the question is asked; relative phrases in the query resolve
    # against it. Defaults to now.
    as_of: AwareDatetime | None = None
    # Hard window on when a memory's event happened (or, lacking one, when it
    # was said).
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None
    # Ask the judge model for up to three rephrasings and fuse their rankings
    # with the original's. Adds one model call; failures fall back silently.
    rewrite_query: bool = False
    budget_tokens: int = Field(default=800, ge=1, le=20_000)
    limit: int = Field(default=30, ge=1, le=200)

    @model_validator(mode="after")
    def _ordered_range(self) -> SearchIn:
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError("since must not be later than until")
        return self


class ForgetIn(StrictModel):
    """Forget matching memories: by a request searched semantically, or by ids.

    Forgetting archives: a forgotten memory leaves search and profiles, keeps
    its history and reason, and a reviewer can bring it back. A dry run is the
    default, because the match is semantic and a broad request selects more
    than intended.
    """

    query: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = None
    ids: list[Identifier] | None = Field(default=None, max_length=500)
    # Narrow to one scope; omitted means every scope the caller may write.
    scope: Slug | None = None
    dry_run: bool = True
    # Minimum hybrid score for a query-mode candidate.
    threshold: float = Field(default=0.3, ge=0, le=2)
    max_forget: int = Field(default=100, ge=1, le=500)
    # Ask the judge model which candidates are really about the request.
    verify: bool = True
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None

    @model_validator(mode="after")
    def _one_selector(self) -> ForgetIn:
        if (self.query is None) == (self.ids is None):
            raise ValueError("give exactly one of query or ids")
        return self


class FeedbackIn(StrictModel):
    memory_id: Identifier
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8192)]
    useful: bool | None = None
    correct: bool | None = None


class RetrievalRunFeedbackIn(StrictModel):
    memory_id: Identifier
    useful: bool | None = None
    correct: bool | None = None


class ProfileIn(StrictModel):
    blocks: list[Literal["about", "style", "team", "project", "recent"]] = Field(
        default_factory=lambda: ["about", "style", "team", "project", "recent"]
    )
    workspace: Slug | None = None
    dynamic_days: int = Field(default=30, ge=1, le=3650)
    budget_tokens: int = Field(default=800, ge=1, le=20_000)
    include_untrusted: bool = False


class EraseIn(StrictModel):
    confirm: Literal["ERASE ALL DATA"]


class ConsolidateIn(StrictModel):
    dry_run: bool = True
    merge: bool = False


class DreamIn(StrictModel):
    # The scope to dream over; omitted means the caller's own.
    scope: Slug | None = None
    max_clusters: int = Field(default=8, ge=1, le=50)
    # Plan clusters without calling a model.
    dry_run: bool = False


class ReplayIn(StrictModel):
    confirm: Literal["REPLAY"] | None = None


class PolicyIn(StrictModel):
    kind: Literal["extraction", "retrieval", "retention", "consolidation"]
    name: ShortText
    version: int = Field(ge=1)
    config: dict[str, Any]
    scope: Slug | None = None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


# Typed dictionaries describe JSON views without inserting absent optional keys.
# Context, job results, model input/output and extensions remain arbitrary JSON.
class View(TypedDict):
    __pydantic_config__ = ConfigDict(extra="allow")


EntityKind = Literal["user", "team", "project", "product", "company", "person", "custom"]
ReviewStatus = Literal["pending", "confirmed", "declined"]
SourceRole = Literal["user", "assistant", "agent", "tool", "manual", "inference"]


class ScopeView(View):
    id: str
    slug: str
    kind: EntityKind
    name: str
    writable: bool


class PrincipalView(View):
    id: str
    handle: str
    display_name: str
    role: Literal["admin", "member"]
    auth_kind: Literal["api_key", "session"]
    own_entity_id: str
    team_entity_id: str | None
    scopes: list[ScopeView]


class UserView(View):
    id: str
    handle: str
    display_name: str
    email: str | None
    role: Literal["admin", "member"]
    created_at: str | None
    disabled_at: str | None
    own_entity_id: str | None
    key_last_used_at: str | None


class ApiKeyView(View):
    id: str
    name: str
    key_prefix: str
    created_at: str | None
    last_used_at: str | None
    revoked_at: str | None


class EntityMemberView(View):
    user_id: str
    handle: str
    display_name: str
    role: Literal["owner", "member", "viewer"]


class EntityView(View):
    id: str
    kind: EntityKind
    name: str
    slug: str
    description: str
    visibility: Literal["members", "team"]
    aliases: list[str]
    writable: bool
    created_at: str | None
    archived_at: str | None
    members: NotRequired[list[EntityMemberView]]


class MemorySummary(View):
    id: str
    text: str
    kind: str
    importance: float
    confidence: float
    review_status: ReviewStatus
    source_role: SourceRole
    status: Literal["active", "archived", "expired", "superseded"]
    scope: str | None
    scope_slug: str | None
    subject: str | None
    subject_slug: str | None
    tags: list[str]
    created_at: str | None
    updated_at: str | None
    revision: int
    document_date: NotRequired[str | None]
    event_dates: NotRequired[list[str]]
    is_static: NotRequired[bool]
    source_count: NotRequired[int]


class MemoryRecord(MemorySummary):
    author: str | None
    context: dict[str, Any]
    valid_until: str | None
    retrieval_count: NotRequired[int]
    last_retrieved_at: NotRequired[str | None]
    judge_run_id: NotRequired[int | None]
    extraction_version: NotRequired[str]
    writable: NotRequired[bool]
    sessions: NotRequired[list[str]]


class EvidenceSpan(View):
    supported_revisions: NotRequired[list[int]]
    evidence_status: NotRequired[Literal["current", "historical", "legacy_unversioned"]]
    message_id: int
    start_char: int
    end_char: int
    excerpt: str
    verified: bool
    role: str
    created_at: str | None


class MemoryRevision(View):
    revision: int
    text: str
    kind: str
    status: str
    review_status: ReviewStatus
    importance: float
    confidence: float
    context: dict[str, Any]
    tags: list[str]
    source_role: str
    extraction_version: str
    created_at: str | None


class SearchEvidence(View):
    message_id: int
    excerpt: str
    role: str
    created_at: str | None
    revision: int | None
    evidence_status: Literal["current", "legacy_unversioned"]
    # The source chunk around the verified excerpt, when requested.
    context: NotRequired[str]
    context_start: NotRequired[int]
    context_end: NotRequired[int]


class LinkedMemory(View):
    id: str
    text: str
    kind: str
    relation: Literal[
        "replaces", "replaced_by", "extends", "extended_by", "derived_from", "premise_of"
    ]
    status: str
    source_role: str
    document_date: str | None
    event_dates: list[str]
    valid_until: str | None


class SearchMemory(View):
    id: str
    text: str
    kind: str
    context: dict[str, Any]
    tags: list[str]
    source_role: SourceRole
    revision: int
    review_status: ReviewStatus
    scope: str | None
    scope_slug: str | None
    subject: str | None
    subject_slug: str | None
    score: float
    similarity: float
    lexical: float
    entity: float
    importance: float
    recency: float
    updated_at: str
    # Added with retrieval policy v2; optional so a client can still read an
    # older server's results.
    document_date: NotRequired[str | None]
    event_dates: NotRequired[list[str]]
    source_count: NotRequired[int]
    is_static: NotRequired[bool]
    temporal: NotRequired[float]
    sources: NotRequired[list[SearchEvidence]]
    history: NotRequired[list[LinkedMemory]]
    related: NotRequired[list[LinkedMemory]]


class ProfileMemory(View):
    id: str
    text: str
    kind: str
    source_role: SourceRole
    review_status: ReviewStatus
    scope: str | None
    subject: str | None
    updated_at: str | None
    document_date: NotRequired[str | None]
    event_dates: NotRequired[list[str]]
    is_static: NotRequired[bool]


class SessionView(View):
    id: str
    user: str | None
    scope: str
    scope_slug: str
    agent_id: str
    started_at: str | None
    ended_at: str | None
    context: dict[str, Any]
    messages: int
    extracted: int


class SessionDetail(View):
    id: str
    user_id: str
    scope_id: str
    agent_id: str
    started_at: str | None
    ended_at: str | None


class MessageView(View):
    id: int
    role: Literal["user", "assistant", "tool"]
    content: str
    created_at: str | None
    processed: bool
    redacted: bool


class JudgeRunView(View):
    id: int
    kind: str
    model: str
    prompt_version: str
    error: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    latency_ms: float | None
    created_at: str | None
    user: NotRequired[str | None]


class JudgeRunDetail(JudgeRunView):
    input: Any
    output: Any


class JobView(View):
    id: str
    kind: str
    status: str
    result: Any
    error: str | None
    error_code: str | None
    created_at: str | None
    finished_at: str | None
    user: NotRequired[str | None]
    events: NotRequired[list[dict[str, Any]]]


class ReviewItem(View):
    id: str
    kind: Literal["memory", "unresolved_mention", "conflict", "failed_job", "budget"]
    title: str
    created_at: str | None
    actions: list[str]
    detail: NotRequired[str | None]
    memory: NotRequired[MemorySummary]
    memory_id: NotRequired[str | None]
    author: NotRequired[str | None]
    subject: NotRequired[str | None]
    previous_text: NotRequired[str | None]
    payload: NotRequired[dict[str, Any]]
    error_code: NotRequired[str | None]


class RetrievalFeedback(View):
    useful: bool | None
    correct: bool | None
    created_at: str | None


class RetrievalResult(View):
    memory_id: str
    rank: int
    feedback: RetrievalFeedback | None
    text: NotRequired[str]
    kind: NotRequired[str]
    source_role: NotRequired[str]


class RetrievalRun(View):
    id: str
    policy_id: str
    created_at: str | None
    used_tokens: int
    abstained: bool
    timings: dict[str, float]
    results: list[RetrievalResult]


class DatabaseHealth(View):
    schema_version: int | None


class VectorHealth(View):
    available: bool
    memories: int | None
    raw: int | None
    error: str | None


class EmbedderHealth(View):
    ready: bool
    device: str | None
    revision: str


class OutboxHealth(View):
    pending: int


class SearchLatency(View):
    p50: float | None
    p95: float | None
    p99: float | None


class IndexCounts(View):
    database_active: int
    qdrant_active: int | None


class BackupView(View):
    id: UUID
    path: str
    kind: str
    sha256: str
    bytes: int
    protected: bool
    created_at: datetime
    verified_at: datetime | None


class SeriesPoint(View):
    date: str | None
    key: str
    value: int | float


class MemoryTotals(View):
    active: int
    pending: int
    archived: int
    superseded: int
    about_someone: int


class PipelineTotals(View):
    month_spend_usd: float
    month_reserved_usd: float
    month_calls: int
    month_errors: int
    acceptance_rate: float | None


class RetrievalTotals(View):
    searches: int
    p50_ms: float | None
    p95_ms: float | None
    abstention_rate: float | None


class ReviewTotals(View):
    pending: int
    oldest_pending: str | None
    pending_by_source: dict[str, int]
    attention_by_kind: dict[str, int]


class EntityUsage(View):
    slug: str
    name: str
    kind: EntityKind
    in_scope: int
    about: int
    members: int
    last_activity: str | None


class PersonUsage(View):
    handle: str
    display_name: str
    role: Literal["admin", "member"]
    disabled: bool
    memories: int
    memories_all_time: int
    sessions: int
    searches: int
    month_spend_usd: float
    key_last_used_at: str | None


class EntityTotals(View):
    entities: list[EntityUsage]


class PeopleTotals(View):
    people: list[PersonUsage]


class StatsOut[T](BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    from_: str | None = Field(alias="from")
    to: str | None
    bucket: Literal["day"]
    series: list[SeriesPoint]
    totals: T


class FlexibleOut(BaseModel):
    model_config = ConfigDict(extra="allow")


class HealthOut(StrictModel):
    ok: bool


class ReadyOut(StrictModel):
    ready: bool
    database: bool
    qdrant: bool
    embedder: bool


class BatchOut(StrictModel):
    items: list[dict[str, Any]]
    count: int


class JobQueuedOut(StrictModel):
    job_id: str | None
    status: str
    reason: str | None = None


class MemoryCreatedOut(StrictModel):
    id: str
    stored: bool
    indexed: bool
    index_job_id: str | None = None
    # True when an identical claim already existed in this scope and was
    # returned instead of a twin being written.
    deduplicated: bool = False
    review_status: str = "pending"


class EntityCreatedOut(FlexibleOut):
    id: str
    slug: str
    kind: EntityKind


class EntityOut(FlexibleOut):
    id: str
    revision: int | None = None
    status: str | None = None


class ItemsOut(StrictModel):
    items: list[dict[str, Any]]


class CursorPageOut(ItemsOut):
    next_cursor: str | None


class OffsetPageOut(ItemsOut):
    total: int
    limit: int
    offset: int


class MemoryOut(StrictModel):
    memory: MemoryRecord


class MemorySourcesOut(StrictModel):
    memory: MemorySummary
    source_role: str
    evidence: list[EvidenceSpan]
    historical_evidence: list[EvidenceSpan] = Field(default_factory=list)


class MemoryHistoryOut(StrictModel):
    memory: MemorySummary
    revisions: list[MemoryRevision]
    predecessors: list[MemorySummary]
    successor: MemorySummary | None


class TemporalWindow(View):
    start: str
    end: str
    phrase: str


class TemporalIntentView(View):
    window: TemporalWindow | None
    order: Literal["earliest", "latest"] | None
    asks_time: bool


class MemorySearchOut(StrictModel):
    # What the query said about time, when it said anything and the policy
    # uses time.
    temporal: TemporalIntentView | None = None
    memories: list[SearchMemory]
    used_tokens: int
    dropped_trust: list[str]
    dropped_validity: list[str]
    dropped_filter: list[str]
    dropped_relevance: list[str]
    policy_id: str
    embed_ms: float
    timings: dict[str, float]
    raw: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_id: str | None = None
    # The rephrasings searched alongside the query, when rewrite_query was set.
    rewrites: list[str] = Field(default_factory=list)


class ForgetCandidate(View):
    id: str
    text: str
    score: float
    scope: str | None


class ForgetOut(StrictModel):
    dry_run: bool
    # Whether the judge model confirmed the query-mode candidates.
    verified: bool
    candidates: list[ForgetCandidate]
    forgotten: list[str]
    reason: str | None = None


class FeedbackOut(StrictModel):
    recorded: bool


class ProfileOut(StrictModel):
    blocks: dict[str, list[ProfileMemory]]
    used_tokens: int
    budget_tokens: int
    generated_at: str
    policy_id: str
    scope: dict[str, Any] | None = None


class SessionOut(StrictModel):
    user: PrincipalView
    csrf_required_header: str = auth.CSRF_HEADER


class KeyCreatedOut(StrictModel):
    id: str
    name: str
    key_prefix: str
    # The only time this value exists outside the caller's hands.
    secret: str


class JobOut(JobView):
    pass


class SessionMessagesOut(OffsetPageOut):
    session: SessionDetail
    items: list[MessageView]


class JudgeRunOut(JudgeRunDetail):
    pass


class AdminHealthOut(FlexibleOut):
    database: DatabaseHealth
    qdrant: VectorHealth
    embedder: EmbedderHealth
    outbox: OutboxHealth
    jobs: dict[str, int]


class MetricsOut(FlexibleOut):
    outbox_pending: int | None
    oldest_unprocessed_message: str | None
    provider_errors: int
    month_spend_usd: float
    month_reserved_usd: float
    month_limit_usd: float | None
    pending_review: int
    search_latency_ms: SearchLatency
    retrieval_runs: int
    abstention_rate: float | None
    feedback_labels: int
    feedback_runs: int
    useful_rate: float | None
    correct_rate: float | None
    spend_by_user: list[dict[str, Any]]
    outbox_oldest_age_seconds: float | None
    outbox_retries: int | None
    index_parity: IndexCounts
    backup_freshness_seconds: float | None


class UsersOut(ItemsOut):
    items: list[UserView]


class ApiKeysOut(ItemsOut):
    items: list[ApiKeyView]


class EntitiesOut(ItemsOut):
    items: list[EntityView]


class EntityProfileOut(FlexibleOut):
    entity: EntityView
    about: list[MemorySummary]
    in_scope: list[MemorySummary]
    budget_tokens: int


class MemoryPageOut(OffsetPageOut):
    items: list[MemoryRecord]


class SessionsOut(OffsetPageOut):
    items: list[SessionView]


class SessionMemoriesOut(FlexibleOut):
    items: list[MemorySummary]
    jobs: list[dict[str, Any]]


class JobsOut(ItemsOut):
    items: list[JobView]


class JudgeRunsOut(ItemsOut):
    items: list[JudgeRunView]


class ReviewQueueOut(ItemsOut):
    items: list[ReviewItem]


class RetrievalRunsOut(ItemsOut):
    items: list[RetrievalRun]


class BackupsOut(ItemsOut):
    items: list[BackupView]


class MemoryStatsOut(StatsOut[MemoryTotals]):
    pass


class PipelineStatsOut(StatsOut[PipelineTotals]):
    pass


class RetrievalStatsOut(StatsOut[RetrievalTotals]):
    pass


class ReviewStatsOut(StatsOut[ReviewTotals]):
    pass


class EntityStatsOut(StatsOut[EntityTotals]):
    pass


class PeopleStatsOut(StatsOut[PeopleTotals]):
    pass
