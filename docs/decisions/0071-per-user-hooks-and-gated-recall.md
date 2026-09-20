# 0071 — Hooks carry a person's key, file into a scope, and may recall on request

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    0058 (configuration, per-prompt injection, profile shape, breaker); the skill-not-runtime and provenance clauses of 0058 stand
    Superseded by: —
    Evidence:      tests/test_claude_code_integration.py, tests/test_remote_client.py
    Code:          integrations/claude-code/hooks/memkit_hooks.py, src/memkit/remote.py, src/memkit/cli.py (install-claude-code), src/memkit/principal.py (scope_for_workspace)
    Contract:      ../03-api.md, decisions/0060, decisions/0061

## Decision

The key a hook sends is a person's identity, not an instance secret. It is read
in one order everywhere — `MEMKIT_API_KEY`/`MEMKIT_BASE_URL` from the
environment, then `~/.config/memkit/client.env`, then the legacy `~/.memkit`
with a one-line notice — by one stdlib-only module, `remote.py`, that the hook,
the Hermes adapter and any future thin client share. The old hook read only
`~/.memkit`, which no command ever wrote, so the documented onboarding produced
hooks that ran, failed open, and stored nothing. A test now asserts the hook
never names a config path itself.

A conversation files into a scope. A repository declares one in `.memkit.toml`
at its root (`entity = "<slug>"`), found by walking up from the working
directory and stopping at the git root. Absent that, the repository's name is
tried as an alias — on the server too, so live capture and a later bulk import
of the same transcripts land in the same place; they used to disagree — and
finally the person's own space. A scope the person cannot write to degrades to
private rather than losing the turn.

The session-start block is five named sections — about you, how you like to
work, team rules, this project, recently — each budgeted, plus one line naming
the active scope so the model can tell private from shared without guessing.
It is re-injected on `compact`, because compaction drops it and nothing else
puts it back.

Recall on each prompt exists, and is off. A repository opts in with
`recall = true`; the hook then abstains on anything under twelve characters or
starting with a slash, fires only on an alias hit or a decision phrase in
English or Russian, spends 200 tokens and 0.4 s, and never re-injects an id
already shown this session. 0058 rejected per-prompt injection on latency and
noise; the answer was a heuristic that abstains, not the absence of the hook.

## Alternatives and why not

**Keep the single instance key and have the hook name its user.** The server
would then trust a header to say who is speaking, which is the one thing a
credential exists to make unnecessary. Per-user keys are decided in 0060; the
hook merely stops pretending otherwise.

**Warn about the legacy config in `doctor` only**, as [8b91822] had moved it.
That was right when the hook was the only reader and the warning fired on
every session. With the resolution in a shared library it prints once per
process, to stderr, under exit 0 — invisible unless someone is looking, and
present exactly when they are.

**Resolve the repository name to a scope in the hook only.** Then the bulk
importer, which shares the classifier but not the hook, files the same
transcripts elsewhere. The fallback belongs where both paths pass: the server.

**Always recall, or never.** Always recall is what 0058 measured and rejected —
a search per prompt is latency the user notices and context they did not ask
for. Never recall leaves a real question ("what did we decide about X?")
answerable only by the model volunteering to search. A gated hook that mostly
does nothing is the shape that survives contact with a user who will otherwise
turn it off.

**A circuit breaker in the skill.** Still rejected, as in 0058: the skill is
prose. The hooks are code and now carry one, copied from the Hermes adapter's
measured shape rather than reinvented.
