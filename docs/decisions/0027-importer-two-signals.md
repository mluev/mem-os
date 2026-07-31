# 0027 — The transcript importer trusts two signals, not one

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: —
    Evidence:      ../measurements.md#frozen-results
    Code:          src/memkit/importers/claude_code.py
    Contract:      ../03-api.md#importing-history

## Decision

A transcript line is imported as a conversational turn only if it passes both a
type check and a content check. Interrupt markers, slash commands, local-command
output, bash I/O, task notifications, compaction summaries, agent briefs, system
prompts, tool results, sidechains and meta lines are all rejected. User turns over
20,000 characters are rejected as documents rather than messages.

## Why two signals

Neither is sufficient alone. The `type` field is absent or misleading on
desktop-SDK turns, so trusting it drops real conversation. Trusting content alone
imports command output, which is where credentials live.

The 20,000-character ceiling exists because three pasted plan documents (78k, 86k
and 129k characters) would otherwise have become "user turns", dominated every
embedding they appeared in, and cost real money to send to the judge as windows.

Measured on the first import: 58,666 transcript lines yielded 4,411 kept turns and
304 indexable ones. The rejection rate is the feature.

## Note

The classifier is the best-tested part of the importer (28 cases) and the file
walk around it is untested — the asymmetry is recorded in
[../08-testing.md](../08-testing.md) rather than hidden.
