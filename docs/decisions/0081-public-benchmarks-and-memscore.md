# 0081 — LoCoMo and LongMemEval with MemScore are the retrieval north star

    Status:        accepted
    Date:          2026-09-29
    Supersedes:    — (the internal golden set and readiness corpora remain regression checks)
    Evidence:      ../../eval/bench/README.md
    Code:          eval/bench/
    Contract:      ../08-testing.md

## Decision

Measure answer quality on the public long-memory benchmarks the field reports:
LoCoMo and LongMemEval, through `python -m eval.bench` against a running
deployment. Each conversation gets its own user; turns keep their recorded
dates; questions are asked at their own date. Report accuracy per category,
evidence recall (retrieval vs answering misses), search latency, context
tokens, and MemScore (`accuracy% / latency ms / context tokens`).

Ranking weights, prompt promotions and new signals are adopted on these runs,
compared with this harness's own earlier runs; comparisons with other systems
state the answering model, judge, prompts and budget.

## Alternatives and why not

**Internal cases only.** 47 cases grounded in one person's corpus cannot
show temporal, multi-session or knowledge-update performance, and cannot be
compared with anyone.

**Accuracy alone.** Any system can buy accuracy with context; MemScore keeps
the cost in the same line.
