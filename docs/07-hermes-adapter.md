# The Hermes adapter

A `MemoryProvider` plugin that gives Hermes Agent memory across sessions. It speaks
HTTP to `127.0.0.1` only and depends on nothing in this repository at runtime.

An earlier version of this document was written before anyone had read the actual
abstract base class, and a plugin built to it would not have instantiated. Every
correction is folded in below rather than annotated; the original is in
[archive/](archive/2026-07-original-spec/07-hermes-adapter.md) if the comparison is
wanted.

## Where it lives

Hermes looks for user plugins in **`$HERMES_HOME/plugins/<name>/`**:

```
~/.hermes/plugins/memkit/
    __init__.py      # MemkitProvider + register(ctx)
    client.py        # stdlib urllib HTTP client + circuit breaker
    scrub.py         # secret redaction
    plugin.yaml      # name/version/description for `hermes memory setup`
```

Not `plugins/memory/<name>/` — that is the *built-in* provider directory inside the
hermes-agent package, and writing there means editing somebody else's package.

The source lives in this repository and `memkit install-hermes` copies it into place.
A **copy, not a symlink**: a symlink into a git checkout means switching branches
silently changes what Hermes loads.

Configuration in `$HERMES_HOME/config.yaml`:

```yaml
memory:
  provider: memkit
plugins:
  memkit:
    base_url: http://127.0.0.1:8077
    owner_id: u-1
    budget_tokens: 800
    prefetch_timeout: 0.4
    send_tool_results: false
    db_path: /path/to/mem-os/data/memkit.db   # for backup_paths
```

Note `base_url` carries **no `/v1` suffix** — the client adds the path. The API key
comes from the `MEMKIT_API_KEY` environment variable, and the variable name itself is
configurable as `api_key_env`.

## Required methods: four, not two

Missing any one of these means the class does not instantiate and the provider
silently does not load:

| method | notes |
|---|---|
| `name` | property |
| `is_available()` | **must make no network call** — the ABC requires it |
| `initialize(session_id, **kwargs)` | kwargs include `agent_context` |
| `get_tool_schemas()` | tool definitions |

`is_available()` making no network call is not a style preference: liveness is the
circuit breaker's job, and a blocking probe here runs on a path that must stay fast.
It returns `False` when no API key is configured, which is a configuration answer
rather than a liveness one.

`initialize` receives `agent_context` — one of `primary`, `subagent`, `cron` or
`flush`. **Only `primary` may write.** A cron job's system prompt is not the user,
and a subagent's conclusions are not either.

Also implemented, and easy to miss:

| method | why it matters |
|---|---|
| `queue_prefetch(query, *, session_id="")` | warms the cache for the next turn |
| `get_config_schema()` / `save_config(values, hermes_home)` | `hermes memory setup` |
| `backup_paths()` | **required** — see below |

## Tool schemas use `parameters`

`get_tool_schemas()` returns dicts keyed **`parameters`**, not `input_schema`. Every
shipped provider does it this way; with the wrong key the tools are accepted and
silently never work, which is the worst available failure mode.

Two tools:

- `memkit_search` — the model sometimes wants a sharper query than the last turn.
  Prefetch searches on the last turn automatically; this is for when that is not what
  the model needs.
- `memkit_remember` — writes directly at high importance, bypassing the judge, and
  declares `source_role="assistant"` because the text is the model's
  ([decisions/0006](decisions/0006-source-role-and-may-write.md)).

## Prefetch

Synchronous, with a **0.4 s** timeout, plus a background warm-up fired from
`initialize`.

The original budget was 0.15 s, reasoned from the embedder at ~30 ms and Qdrant at
~10 ms. That costed the in-process work rather than an HTTP round trip to a service
that may have just started: measured, ~840 ms cold and 75–93 ms warm. The fix is the
warm-up, not a wider timeout — a timeout generous enough for the cold case would make
every warm turn wait on budget it does not need
([decisions/0040](decisions/0040-prefetch-timeout-and-warmup.md)).

Two rules, both absolute:

- **It never raises.** On timeout it serves a per-query cache, then a last-result
  cache, then an empty string.
- **It never wraps the result in a `<memory_context>` tag.** Hermes composes the
  prompt; the provider returns content.

Without the warm-up, the first turn after every restart silently has no memory. That
is not hypothetical — it is what happened on the first live run, and it is why
[decisions/0025](decisions/0025-eager-embedder-load.md) also loads the model eagerly
on the service side. Two mechanisms, because the failure is silent.

## What is sent

### Tool results are not, by default

`send_tool_results` defaults to `false`. Tool output is where credentials actually
appear — command output, environment dumps, file contents — and this is a structural
bar rather than reliance on pattern matching
([decisions/0042](decisions/0042-no-tool-results-by-default.md)).

### Redaction is the second line, and it has already missed once

`scrub.py` applies ten ordered patterns: OpenAI-style keys, AWS access keys, GitHub
tokens, Google keys, JWTs, bearer headers, PEM private-key blocks, `user:pass@` in
URLs, and any `NAME=value` assignment whose name contains `secret`, `token`,
`password`, `api_key`, `credential` or similar.

That last pattern was originally **anchored to the start of a line**. The unit test
passed because the test author had written the key on its own line. On the first live
checklist run, a key pasted mid-sentence — "here's the key `AWS_SECRET_ACCESS_KEY=…`,
put it in prod" — reached the database untouched.

The fix matches an assignment anywhere in the text and replaces the value rather than
the line. **The lesson is about test authorship, not regexes:** the test and the code
were written by the same person in the same sitting, against the same mental model of
what the input looks like. A table-driven test with one row per secret shape, written
from the attacker's side rather than the author's, is the form that catches this.

### Idempotency

`external_id = sha256(f"{session_id}|{role}|{body}")[:32]`, with
`external_source="hermes"`. The service has a unique index on the pair and answers a
repeat with `deduplicated: true`.

A content hash rather than a message id, because Hermes does not expose a stable one
at the point the turn is sent. Note the transcript importer uses a different identity
— the transcript line's own `uuid` — so the two ingest paths are idempotent by
different means. Both are correct for their source; neither generalises to the other.

Verified live: one turn sent twice left exactly one pair of messages.

## `backup_paths`

`hermes backup` only walks `HERMES_HOME`. memkit's SQLite file and Qdrant storage
live outside it, so an undeclared path means backup and restore silently lose every
fact — the failure appears at restore time, which is the worst possible moment.

The method must work **without** `initialize()` and without network access. It reads
configuration only.

## The circuit breaker

Five consecutive failures open the circuit for two minutes.

**Only 5xx and network errors count.** A 4xx is the service answering: an unknown id
or a rejected body is information, not an outage, and letting them open the circuit
would take memory down over a malformed request.

This has a consequence worth knowing about: a misconfigured API key produces 401 on
every call, never opens the circuit, and — because `prefetch` never raises — degrades
to permanent silent memory loss with nothing logged as an error. The rule is still
right; the observability gap around it is real.

## Duplicated history is fine

Hermes keeps its own `messages` table with FTS5. memkit keeps its own. For Hermes it
is conversation history to search; for memkit it is raw material for re-extraction
and provenance. The only requirement is that the link is explicit, and `external_id`
provides it.

## Acceptance checklist

All verified, with automated coverage in `tests/test_hermes_provider.py`.

- [x] Service stopped — the agent still works; prefetch returns an empty string.
- [x] Service unresponsive — prefetch serves the cache, then empty. Never raises.
- [x] One turn sent twice — exactly one pair of messages.
- [x] `AWS_SECRET_ACCESS_KEY=…` **in a user turn, mid-sentence** — redacted.
      *This one caught a real defect.*
- [x] `on_session_end` calls `POST /v1/sessions/{id}/close`.
- [x] The provider loads through Hermes's own mechanism, `is_available()` is true,
      and both tools are visible.
- [x] A fact stated in one session surfaces in another agent's session.

The last item is the goal of the whole project, so it was verified end to end rather
than in parts: a chat session was told a specific personal preference, `on_session_end`
forced tail extraction with the real judge, and a second provider in a separate coding
session retrieved that fact at rank 1.

### One check that was dropped

The original list included: **interrupted turn → nothing written to memory.** It is
not in the current list and it is not covered by a test.

It is worth restoring. An interrupted turn is a partial statement, and a partial
statement is exactly the kind of thing that reads as a preference without being one —
"actually, let's not use" cut off mid-sentence is a fact with its meaning removed.
Recorded here rather than quietly omitted.
