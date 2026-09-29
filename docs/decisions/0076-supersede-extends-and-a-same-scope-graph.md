# 0076 — Supersession keeps the past; links never cross a scope

    Status:        accepted
    Date:          2026-09-29
    Supersedes:    — (extends 0064; the in-place UPDATE remains for corrections)
    Evidence:      ../research/2026-09-29-supermemory.md
    Code:          store.py (add_relation, supersede, history_of, reinforce), extract.py, graph.py
    Contract:      ../02-data-model.md, ../05-retrieval.md

## Decision

An UPDATE says what kind of change it is. `correction`: the candidate was
wrong, and its text is rewritten in place with a revision, as before.
`supersede`: the candidate was true until something changed — a new memory is
written with its own date and evidence, the old one becomes `superseded`, its
`valid_until` is set to the replacement's `document_date`, and an `updates`
edge links them. An ADD may name the candidate it `extends`.

Edges live in `memory_relations` (`updates`, `extends`, `derives`), only ever
between two memories of one scope, cascade with either end, and are
re-checked against the caller's scopes on every read. A duplicate that arrives
from a session the memory does not cite yet raises `source_count`, so
repetition across conversations is counted once per conversation.

## Alternatives and why not

**Always rewrite in place.** The previous value survives only in revisions,
which search cannot see, so "where did I live before Lisbon?" has no answer.

**Always write a new memory.** A typo fix would leave a false claim in history
as though it had once been true, and ids would churn for every correction.

**Cross-scope edges.** An edge from a team fact to a private one is a path by
which the private one could be revealed, and it outlives erasure of one side.
