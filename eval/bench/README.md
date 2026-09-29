# Public benchmarks: LoCoMo and LongMemEval

`python -m eval.bench` measures a running Mem OS the way memory products are
compared publicly (Supermemory's MemoryBench, Mem0 and Zep's papers): ingest the
benchmark's conversations, let the service extract, search once per question,
answer only from what search returned, and have a model judge the answer.

It drives the public HTTP API, so it measures the deployed system: the worker,
the extractor prompt, Qdrant and the embedding model, not a test double.

## What it reports

- **accuracy**, overall and per question category;
- **evidence recall**: whether search returned the turns (LoCoMo) or sessions
  (LongMemEval) the dataset marks as containing the answer. This separates a
  retrieval miss from an answering miss;
- **latency** (mean, p50, p95 of the search call) and **context tokens** handed
  to the answering model;
- **MemScore** — `accuracy% / latency ms / context tokens`, the composite
  Supermemory's MemoryBench reports, so quality is never quoted without its
  cost.

## Running

The service needs a judge configured (`GEMINI_API_KEY` or `ANTHROPIC_API_KEY`)
and a monthly ceiling large enough for the run: LoCoMo (10 conversations, ~5.9k
turns) is roughly 600 extraction windows; LongMemEval-S gives each of its 500
questions its own ~50-session haystack, so sample it with `--limit` or
`--categories` first.

```sh
uv run python -m eval.bench download locomo --out data/bench/locomo10.json
# LongMemEval-S (HuggingFace):
uv run python -m eval.bench download longmemeval --out data/bench/longmemeval_s.json

export MEMKIT_BASE_URL=https://memory.example.com
export MEMKIT_ADMIN_KEY=mk_...           # an administrator's key
export GEMINI_API_KEY=...                # for the answering and judging models

uv run python -m eval.bench run --dataset locomo --data data/bench/locomo10.json \
    --run-id locomo-v11 --limit 200
uv run python -m eval.bench report --run-id locomo-v11
```

Useful options: `--mode memories|hybrid|raw` (facts, facts plus raw user
passages, or raw passages only — the baseline every memory system must beat),
`--rewrite` (query rewriting with rank fusion), `--budget` (context tokens per
question), `--answer-model` / `--judge-model` (any `gemini-*` or `claude-*`
model the providers module supports), `--categories temporal,multi-hop`.

## Isolation and state

Each conversation gets its own user, created with the administrator key, so
dedup candidates, supersession targets and dreaming never see another
conversation. The users remain after the run; erase them with
`memkit erase --user bench-<run>-<conversation> --confirm ERASE`.

Runs checkpoint to `data/bench-runs/<run-id>/state.json` (git-ignored, written
0600 because it holds the per-conversation API keys). An interrupted run
resumes where it stopped; `report` re-summarises without calling anything.

## Reading the numbers

LoCoMo's two speakers are both people and are ingested as named user turns,
because only user words can support a memory here. LongMemEval keeps its roles,
so its `single-session-assistant` questions — about what the assistant said —
can only be answered from raw passages (`--mode hybrid`): the service does not
turn an assistant's words into memories, by design (decisions/0006).

A published number from another system used its own answering model, judge,
prompts and context budget. Compare runs of this harness with each other;
compare with others only with those differences stated.
