# 0010 — `thinking_level=MINIMAL`, because reasoning bills as output

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: —
    Evidence:      ../measurements.md#cost
    Code:          src/memkit/providers.py
    Contract:      ../04-judge.md#cost-shape

## Decision

Gemini calls set `thinking_config=ThinkingConfig(thinking_level="MINIMAL")`, and
output tokens are counted as `candidates_token_count + thoughts_token_count`.
Anthropic calls set `output_config={"effort": ...}` for Sonnet and Opus but not for
Haiku 4.5, which rejects the field.

## Why

Output is priced eight times higher than input on Flash-Lite, and on Gemini
reasoning tokens bill as output. So a model that thinks at length about whether a
window contains a durable fact costs several times what one that answers costs, for
a task whose correct answer is usually "nothing".

Counting `thoughts_token_count` as output is the other half. Omitting it makes
every cost figure an undercount, and the monthly ceiling is enforced against those
figures — so an undercount does not just mislead a dashboard, it disables the
budget guard.

The same reasoning drives the 200-character cap on fact length in the prompt: it
bounds output directly.
