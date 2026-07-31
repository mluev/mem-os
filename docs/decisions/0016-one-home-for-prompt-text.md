# 0016 — `judge.build_prompt()` is the only path to prompt text

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: —
    Evidence:      ../experiments/extractor-prompts.md
    Code:          src/memkit/judge.py, src/memkit/prompts.py
    Contract:      ../04-judge.md#the-prompt

## Decision

`prompts.REGISTRY` holds every prompt version and `judge.build_prompt()` is the
only way to obtain prompt text. No document reproduces it;
[04-judge.md](../04-judge.md) describes the prompt's *shape* and which rules are
load-bearing, and points at the code for the words. The invariant is pinned by
`test_production_prompt_is_the_active_registry_version`.

## Why this is a decision and not an obvious housekeeping rule

Because it was violated, expensively. `judge.py` held its own copy of the prompt —
verbatim v2 plus a task-status block — while stamping every extracted fact with
`prompts.DEFAULT_VERSION`, then `"v4"`. `prompts.render()` was called only by the
two eval scripts. So production ran v2, labelled its output v4, and every measured
comparison of v3, v4 and v5 described a prompt that had never processed a real
message. Twelve judge runs and two facts had to be relabelled.

The current documentation was still carrying a third variant: an eight-rule block
with the language rule at position 7, matching no version in the registry. v6 has
ten rules, no language rule, and a 200-character cap as rule 1.

A prose copy of code rots silently because nothing compares the two. The rule is
therefore structural rather than a matter of discipline: there is one copy, so
there is nothing to diverge.
