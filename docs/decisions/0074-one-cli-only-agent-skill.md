# 0074 — One agent-neutral, CLI-only Memkit skill

    Status:        accepted
    Date:          2026-09-23
    Supersedes:    0058 (skill content: curl examples and the HTTP fallback)
    Superseded by: —
    Evidence:      tests/test_claude_code_integration.py, cli/tests/test_cli.py, cli/tests/test_audit.py
    Code:          skills/mem-os/, cli/src/memos_cli/agents.py, tools/sync_cli_assets.py, src/memkit/cli.py (install-claude-code)
    Contract:      ../../cli/README.md

## Decision

Ship one skill, `skills/mem-os/`, for every agent:

- `SKILL.md` covers the everyday routine, the rules and a capability map.
- `references/` holds three focused guides: memory and retrieval, continuous
  synchronization, and setup and operations.
- The skill id stays `mem-os`, so existing installations upgrade in place. It
  is presented as Memkit.

The skill uses only the `memos` CLI. The CLI owns transport, credentials,
connection choice and repository defaults, so the skill teaches no URLs, keys
or request bodies. The HTTP fallback is removed.

Packaging:

- The CLI wheel carries a byte-identical copy in `memos_cli/assets/skill/`.
  `tools/sync_cli_assets.py --check` fails on missing, changed or stale files.
- The server wheel force-includes the folder as `memkit/agent_skill/mem-os` for
  the legacy `install-claude-code`.
- `memos agents install` copies the whole tree for Claude, Hermes, Codex and
  `--skills-dir`, and backs up any file it replaces or retires.

No API, CLI command or lifecycle adapter was added.

Synchronization stays honest:

- Agents with an active adapter do not upload. Others upload original turns
  with stable identifiers through `memos evidence batch` and close the session.
- Stored evidence is not reported as extracted.
- There is no offline queue.

## Alternatives

- **Keep the canonical copy in the Claude Code folder.** Rejected: the skill
  serves every agent, and a Claude-specific home made it read as Claude-only.
  It also left the legacy installer and the CLI wheel copying two
  separately-named single files instead of one folder.
- **Keep the HTTP fallback.** Rejected: it duplicated connection resolution the
  CLI already does, and taught agents raw requests that bypass CLI safeguards
  (repository scope defaults, erase confirmation, bounded waits).
- **A larger single file.** Rejected: agents read `SKILL.md` on every trigger;
  detail lives in references that are opened only when needed.
