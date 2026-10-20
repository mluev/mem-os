# 0087 — Private spans never leave; injected memory is never evidence

    Status:        accepted
    Date:          2026-10-19
    Supersedes:    —
    Evidence:      —
    Code:          security.py (PATTERNS, strip_injected), store.py (add_message), integrations/hermes/memkit/scrub.py, integrations/claude-code/hooks/memkit_hooks.py
    Contract:      ../02-data-model.md

## Decision

Text wrapped in `<private>…</private>` is replaced by `[PRIVATE]` before
persistence and before any provider call, on the server and in the client
scrub, ahead of every other pattern. Memory blocks the service injected into an
agent's context — `<mem-os-context>`, `<mem-os-recall>` and Hermes'
`<memory-context>` — are replaced by a short marker when a captured turn carries
them, and the Claude Code recall output is tagged so it can be recognised.

## Why

Assistant info as evidence (0082) makes the route from retrieved memory back
into evidence shorter; a captured copy of an injected block would be the
shortest. Neither transcript format is known to carry them today, which is why
this is a cheap guard rather than the main defence.
