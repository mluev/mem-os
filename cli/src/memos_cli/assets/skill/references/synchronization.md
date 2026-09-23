# Continuous synchronization

Memkit learns from conversations: original turns are stored as evidence, and
background extraction turns them into facts, decisions and preferences with
citations. Keep every meaningful conversation synchronized, exactly once.

## 1. Detect automatic capture first

```bash
memos agents status --json
```

- **Claude Code** with `hooks` listed and `disabled: false`: turns are captured
  on stop, before compaction and at session end, and the session is closed
  automatically.
- **Hermes** with `bridge: true`: the Memkit memory provider captures turns.
- **Anything else** (Codex, custom agents, scripts, a disabled adapter): nobody
  captures for you. Use the manual flow below.

Never upload turns that an active adapter already captures; duplicates add noise
to extraction.

Respect repository settings in `.memkit.toml` (at the repository root):

```toml
[memkit]
entity = "mem-os"   # default shared scope for this repository
capture = false     # do not upload conversations from here
recall = true       # adapters may search on each prompt
```

When `capture = false`, do not upload evidence from that repository. Explicit
saves still work if the user asks for them.

## 2. Manual capture

Write original turns to a JSON file and upload them in batches of at most 100
events:

```json
{
  "events": [
    {
      "session_id": "codex-2026-09-23-invoice-fix",
      "agent_id": "codex",
      "external_source": "codex",
      "external_id": "codex-2026-09-23-invoice-fix:1",
      "role": "user",
      "content": "We always bill on the 1st, and Sasha owns the invoice job.",
      "context": {"source_workspace": "billing-service"}
    },
    {
      "session_id": "codex-2026-09-23-invoice-fix",
      "agent_id": "codex",
      "external_source": "codex",
      "external_id": "codex-2026-09-23-invoice-fix:2",
      "role": "assistant",
      "content": "Understood. I'll move the job's schedule to the 1st."
    }
  ]
}
```

```bash
memos evidence batch --data @events.json --json
memos evidence add --data @event.json --json
```

Rules:

- **Original words only.** `content` is the turn as it was said. Never upload
  your own summary as a `user` turn, and never merge several turns into one.
- **Roles** are `user`, `assistant` or `tool`. Prefer user and assistant turns.
  Leave out tool output unless the user asks for it, and never upload secrets,
  credentials or tokens.
- **Stable identifiers.**
  - `session_id`: fixed for the whole conversation.
  - `agent_id` and `external_source`: name your agent.
  - `external_id`: unique and deterministic per turn, for example
    `<session>:<turn number>`.

  With stable identifiers, a retried upload is recognized instead of
  duplicated.
- **Scope.** The CLI does not add a scope to events for you.
  - With no `scope`, an event is private. The exception is when its
    `context.source_workspace` is a registered alias of an entity you can write
    to; then it is filed there.
  - Add `"scope": "SLUG"` only when the conversation belongs to that shared
    entity, for example the repository's `.memkit.toml` `entity` or the user's
    explicit request.
  - An explicit scope you cannot write to fails the whole batch.
- **Timing.** Upload new turns incrementally:
  - after meaningful exchanges, such as a decision, preference, correction or
    new fact;
  - before handing off to another agent or person;
  - before context compaction or truncation;
  - at the end of the task.

  Upload each turn once. Keep track of the last `external_id` you sent.

## 3. Close the session

```bash
memos sessions close SESSION_ID --json
```

Closing flushes the rest of the session to extraction. Close only after every
batch for that session succeeded. If a batch failed, leave the session open,
upload again (same identifiers), then close.

## 4. Stored is not extracted

A successful upload means the evidence is stored. Indexing and extraction run
as background jobs:

```bash
memos jobs list --status running --json
memos jobs get JOB_ID --wait 60 --json
memos sessions memories SESSION_ID --json
memos sessions messages SESSION_ID --json
memos sessions list --limit 10 --json
```

- Say "the conversation is saved; facts will appear once extraction finishes"
  unless a job has completed.
- `sessions memories` shows what was extracted from a session.
- `sessions messages` shows what was stored.
- `memos jobs cancel JOB_ID --json` stops a queued job only when the user asks.

## 5. Recovery and outages

- A batch is stored all or nothing. After a failure or timeout, re-send the same
  events with the same `external_id` values. Turns that were already stored come
  back `deduplicated` instead of being stored twice.
- There is no offline queue and no background retry. If Memkit stays
  unavailable, keep working and tell the user which turns or facts were not
  saved.
- Do not claim hooks, schedules or automatic synchronization that
  `memos agents status` does not show.
- If an adapter is installed but inactive, suggest `memos agents install`
  ([setup-and-operations.md](setup-and-operations.md)); do not edit agent
  settings yourself unless asked.
