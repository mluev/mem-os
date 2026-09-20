# 0058 — Claude Code surface: one skill, three hooks, honest provenance

    Status:        accepted
    Date:          2026-08-28
    Supersedes:    —
    Superseded by: 0071 (configuration, per-prompt injection, profile shape, breaker)
    Evidence:      tests/test_claude_code_integration.py
    Code:          integrations/claude-code/, src/memkit/cli.py (install-claude-code)
    Contract:      ../03-api.md, decisions/0006

## Decision

Agents reach Mem OS through curl and hooks, not a new runtime. The repo ships
`integrations/claude-code/` (packaged into the wheel like the Hermes adapter),
and `memkit install-claude-code` copies it system-wide: one `mem-os` skill into
`~/.claude/skills/` and one hook script into `~/.claude/memkit/`, then prints —
never writes — the `settings.json` hooks snippet.

**One skill, not four.** Save, search, capture, and profile share one config
block and one curl pattern; splitting them would quadruplicate discovery text
around ten-line bodies. The skill is instructions only: config from
`MEMKIT_API_KEY`/`MEMKIT_BASE_URL` then `~/.memkit`, a health preamble, and
the rule that a dead service degrades silently and an empty search result
means "no memory", not an error — abstention is a feature.

**Provenance vocabulary for agent writes** (the commitment this ADR exists
for, extending 0006): a fact the *user told the agent to remember* is written
as `source_role: "manual"` — exactly provenance.py's definition, a key-holder
assertion with no message behind it, trusted by retrieval. It is NOT `user`:
`user` implies message-backed evidence and there is none. A fact the *agent
decided on its own* to keep is `agent`, excluded from default retrieval by
design, and the skill says so. Bulk "remember this conversation" goes through
`/v1/evidence/events:batch` instead of hand-written memories, so extraction,
citation, and redaction all run server-side.

**Hooks** (per the accepted plan: SessionStart + capture, no per-prompt
injection): `session-start` renders the profile into a `<mem-os-context>`
block — the facts with no query semantically near them, attached once per
session; `capture` (Stop) posts the transcript delta as one idempotent
evidence batch; `session-end` captures the final delta and closes the session
so the extraction tail runs. All three fail open with short timeouts: memory
must never block the session it is remembering.

Capture reuses `memkit.importers.claude_code.classify` — the installer pins
the hook command to the interpreter that has memkit installed — so the hook
and the bulk importer share one definition of a real turn and one
`external_id` scheme (the transcript line uuid). The cursor is a byte offset
per session, advanced only after every batch lands; idempotency keys absorb
any overlap.

## Rejected

An MCP server (a second runtime for zero new capability over HTTP + skill),
per-prompt injection (latency and noise the user declined), automatic editing
of `~/.claude/settings.json`, and a circuit breaker in the skill (the Hermes
adapter needs one because it is code; the skill is prose telling an agent to
degrade silently).
