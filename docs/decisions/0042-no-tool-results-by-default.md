# 0042 — `send_tool_results` defaults to false

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: —
    Evidence:      —
    Code:          integrations/hermes/memkit/__init__.py, scrub.py
    Contract:      ../07-hermes-adapter.md#what-is-sent

## Decision

Tool messages are not forwarded to memkit unless `send_tool_results` is explicitly
enabled. When enabled they are scrubbed like any other content and stored with
`role="assistant"`.

## Why a structural bar rather than reliance on scrubbing

Tool output is where credentials actually appear: command output, environment
dumps, file contents. Scrubbing is ten ordered regexes, and regexes have already
missed once here — the `NAME=value` pattern was anchored to the start of a line, the
unit test "covered" it because the test author put the key on its own line, and on
the first live checklist run a key pasted mid-sentence reached the database
untouched.

The lesson recorded at the time was about test authorship rather than regexes, and
it is the right lesson. But it also argues for not depending on the regexes for the
highest-risk content class. Not sending tool output is a bar that cannot be defeated
by a pattern that does not match.

The cost is real: tool output sometimes contains genuinely useful context about how
the user works. The flag exists so that can be enabled deliberately, by someone who
has read this.
