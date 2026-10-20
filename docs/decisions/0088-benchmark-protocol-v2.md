# 0088 — Benchmark protocol v2: own-scope search, reuse, stratified samples, paired tests

    Status:        accepted
    Date:          2026-10-19
    Supersedes:    —
    Evidence:      to be measured; see ../measurements.md#to-be-re-measured
    Code:          eval/bench (client.py, pipeline.py, stats.py, __main__.py), telemetry.py (search_latency_by_stage), retrieval.py (rerank_ms, fuse)
    Contract:      ../../eval/bench/README.md, ../08-testing.md

## Decision

Searches name the conversation's own scope and the report counts what
extraction routed to the team. `--sample` with `--seed` picks the same questions
per category everywhere, and `weighted_accuracy` reweights them to the dataset.
`--source-run` reuses a run's users to compare retrieval settings on identical
memories. `compare` reports the paired difference, a 95% bootstrap interval and
McNemar's exact p. The headline never counts LoCoMo's adversarial questions;
LongMemEval's single-session-assistant questions are included and reported both
ways. `--dream` dreams until caught up before asking. Runs record the server's
settings, spend and per-question timings; search reports per-stage latency, and
a cross-encoder runs once on fused rewrites.

## Why

memorybench's own fix (#96) moved Supermemory's LoCoMo score from 52.8% to
68.8%: the protocol matters as much as the system. A default flips only on a
paired difference whose interval excludes zero; at 200 questions that interval
is about ±5 points, which is what the sample sizes in measurements.md are sized
against.
