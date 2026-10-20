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
  cost;
- **accuracy_excluding_assistant**, the figure comparable across prompt
  versions that can (v12) and cannot (v10, v11) answer what the assistant said,
  and **weighted_accuracy**, a sampled run reweighted to the full dataset's
  category mix so it can be held against published micro-averages;
- **team_routed**, facts the extractor filed into the team scope, which an
  own-scope search cannot see;
- **spend**: server-side model spend during ingestion and search (from
  `/v1/admin/metrics`, so a dedicated deployment is exact), and the answering
  and judging models' spend, capped by `--budget-usd`;
- the server's prompt version, default policy, dreaming mode and reranker, read
  from `/v1/admin/health` and stored with the run.

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
    --run-id locomo-baseline --limit 200
uv run python -m eval.bench report --run-id locomo-baseline
```

To decide the opt-in features, compare runs on the same questions. Extraction
happens at ingestion, so a prompt version needs its own ingest (restart the
app with `MEMKIT_PROMPT_VERSION=v12`, and `MEMKIT_INDEX_ASSISTANT_TURNS=true`
for assistant passages). Retrieval settings do not: `--source-run` searches
again over a previous run's users without ingesting, so a policy, `--rewrite`,
a reranker or `--mode` is compared on exactly the same memories.

```sh
uv run python -m eval.bench run --dataset locomo --data data/bench/locomo10.json \
    --sample "*=50" --seed 1 --run-id lc-v10
uv run python -m eval.bench run --dataset locomo --data data/bench/locomo10.json \
    --sample "*=50" --seed 1 --source-run lc-v10 --run-id lc-v10-v2 --policy core-retrieval-v2
uv run python -m eval.bench compare lc-v10 lc-v10-v2
```

`compare` pairs the questions both runs judged and reports, overall, without
assistant questions and per category: both accuracies, the difference, a 95%
bootstrap interval for it, how many questions were gained and lost, and the
exact McNemar p-value. At 200 questions the interval is about ±5 points;
anything smaller is not a result.

`--dream` dreams each conversation's scope until the job reports `caught_up`
before any question is asked (the server needs a judge). Run it last on a
family of runs: it changes the users that `--source-run` adopts, and later
runs record `dreamed` so a contaminated arm is visible.

Useful options: `--mode memories|hybrid|raw` (facts, facts plus raw
passages, or raw passages only — the baseline every memory system must beat),
`--rewrite` (query rewriting with rank fusion; memories mode only),
`--policy` (retrieval policy for every search; `assistant-v3` also returns
assistant memories and passages), `--budget` (context tokens per question),
`--results` (search limit, 30 as in memorybench), `--answer-model` /
`--judge-model` (any `gemini-*` or `claude-*` model the providers module
supports), `--categories temporal,multi-hop`, `--sample` with `--seed`
(deterministic per-category sampling), `--budget-usd`.

## Isolation and state

Each conversation gets its own user, created with the administrator key, so
dedup candidates, supersession targets and dreaming never see another
conversation. Every user also joins the instance's team scope, which is
system-managed, so each search names the conversation's own scope: a fact
routed to the team is lost to its conversation (counted as `team_routed`)
rather than visible to all of them. The other users still appear in each
extraction's ENTITIES block, which costs tokens; run on a dedicated
deployment. The users remain after the run; erase them with
`memkit erase --user bench-<run>-<conversation> --confirm ERASE`.

Runs checkpoint to `data/bench-runs/<run-id>/state.json` (git-ignored, written
0600 because it holds the per-conversation API keys). An interrupted run
resumes where it stopped; `report` re-summarises without calling anything.

## Reading the numbers

LoCoMo's two speakers are both people and are ingested as named user turns.
Its adversarial questions are left out unless `--adversarial` is given, and
never count toward the headline accuracy. LongMemEval keeps its roles, and its
`single-session-assistant` questions — about what the assistant said — are
included by default: prompt v12 can answer them from assistant info, with
`--policy assistant-v3` (and `MEMKIT_INDEX_ASSISTANT_TURNS=true` for hybrid
mode); v10 and v11 cannot (decisions/0082). Compare prompt versions on
`accuracy_excluding_assistant`, and report the category on its own.
`--no-assistant` leaves them out.

The run's config records the dataset's sha256: the download URLs follow each
dataset's main branch, so compare runs only when the hashes match.

A published number from another system used its own answering model, judge,
prompts and context budget. Compare runs of this harness with each other;
compare with others only with those differences stated.
