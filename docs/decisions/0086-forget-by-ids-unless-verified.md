# 0086 — Unverified forget matches are never applied; apply the dry run's ids

    Status:        accepted
    Date:          2026-10-19
    Supersedes:    —
    Evidence:      —
    Code:          routers/memory.py (forget_memories)
    Contract:      ../05-retrieval.md, ../../skills/mem-os/references/memory-and-retrieval.md

## Decision

`POST /v1/memories/forget` with a query and `dry_run=false` returns 409 when the
judge did not verify the matches — none configured, or `verify=false` — and
something matched. The dry run's candidate ids are what gets applied.

## Why

Without verification what remains is a similarity threshold, exactly the broad
match a person has to look at first. Supermemory's MCP server made the same
change (forget by id after a dry run, "to avoid selection drift").
