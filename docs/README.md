# memkit — design documentation

One memory service for every agent. Local embeddings, a cloud judge, SQLite as the
source of truth.

Agents never touch the database directly, only the API. One instance serves the chat
assistant, the coding agent and anything else, because a memory only one agent can
read is a worse version of that agent's own scratchpad.

## The five invariants

Break any of these and the rest of the design stops holding.

1. **SQLite is the source of truth. Qdrant is a derived index.**
   Qdrant must rebuild from SQLite with one command. That is what makes the
   embedding model and the extractor prompt safe to change — and if the index were
   authoritative for anything, changing either would be irreversible.

2. **Raw messages are never deleted.**
   The extractor prompt will be rewritten many times, and each rewrite has to be
   able to replay the entire history.

3. **`owner_id` is everywhere from day one.**
   There is one user. Adding the column later would be a data migration and a
   rewrite of every query; adding it now costs nothing.

4. **A fact may not derive solely from the assistant's own words.**
   Otherwise the system begins confirming its own hallucinations and there is no way
   to find where the loop started. Enforced at the write, not in the prompt — a
   prompt rule is a request. See
   [decisions/0006](decisions/0006-source-role-and-may-write.md).

5. ~~Everything that happens goes into an append-only journal.~~
   **Declined**, with reasoning, at
   [decisions/0007](decisions/0007-no-events-journal.md). Audit is served by
   `judge_runs`, `memory_sources` and the supersession chain.

The fifth is struck through rather than deleted, because of how it went missing the
first time. An earlier version of this file was headed "three rules" above a list of
five — a typo in the heading. When the list was later trimmed to match the heading,
invariants 4 and 5 went with it, and neither the code nor any document recorded that
anything had been dropped. **A heading typo ate two invariants.** Whatever is
declined here stays visible and struck through.

## Reading order

| | | |
|---|---|---|
| 1 | [01-architecture.md](01-architecture.md) | components, the write and read paths, what memory is not for |
| 2 | [02-data-model.md](02-data-model.md) | SQLite schema, both Qdrant collections, provenance, migrations |
| 3 | [03-api.md](03-api.md) | HTTP and CLI contract, error semantics |
| 4 | [04-judge.md](04-judge.md) | extractor and consolidator contracts, the gate, cost shape |
| 5 | [05-retrieval.md](05-retrieval.md) | scoring, filtering, dedup, budget — the hardest part |
| 6 | [06-roadmap.md](06-roadmap.md) | stages, exit criteria, per-item state, open work |
| 7 | [07-hermes-adapter.md](07-hermes-adapter.md) | the `MemoryProvider` plugin and its acceptance criteria |
| 8 | [08-testing.md](08-testing.md) | four layers, mapped to real test files, with the gaps named |

Alongside them:

- **[measurements.md](measurements.md)** — every number produced by running
  something, dated, with the command that produced it. Nothing else holds a measured
  figure.
- **[decisions/](decisions/)** — why things are the way they are, including what was
  declined and what would reopen it.
- **[experiments/](experiments/)** — dated lab notebooks. Frozen results, never
  updated.
- **[archive/](archive/)** — the original Russian specification, written before any
  code existed. Non-normative and kept unchanged; it records what was argued at the
  time, which a rewrite would turn into a paraphrase.

## Where a fact lives

The rule exists because it was broken, and the breakage is instructive: three
generations of these documents coexisted, each stating things as fact, and between
them they asserted three different judge models, four different corpus sizes and a
prompt that matched no version in the code.

Every one of those was true when written. None was true when read.

| genre | home | the question it answers |
|---|---|---|
| contract | `01`–`08` | would this change if I changed the code? |
| measurement | `measurements.md` | would this change if I re-ran the eval? |
| decision | `decisions/` | would this change if I changed my mind? |
| investigation | `experiments/` | is this a story about how we found out? |

Three rules enforce it, and
[decisions/0002](decisions/0002-four-genre-documentation.md) explains each:

- **No inline amendments** in the numbered documents. No "correction:", no "actually
  implemented as". An annotation leaves the wrong sentence standing beside the right
  one. Edit the document. `tests/test_docs_contract.py` fails on the specific words.
- **Code comments cite decision ids**, never document paths — a path is a
  maintenance surface, an accepted decision never moves.
- **No prompt text in prose.** One copy, in `prompts.REGISTRY`.

## What is checked automatically, and what is not

The machine-checkable parts of these documents are generated from the code and
compared on every test run: the retrieval weights and half-lives, the vocabularies,
the schema, the route table, the configuration defaults, the prompt registry.

```bash
python -m tools.docblocks --check
```

Three classes of claim this cannot cover, stated plainly so nobody assumes the
documents are self-verifying:

**Measured numbers.** A test cannot know a measurement is stale, and re-measuring in
CI costs money and is nondeterministic — the extractor bench varies by more than 2×
between runs on the same input. The convention instead is a marker:
`<!-- measured: 2026-07-31 · uv run memkit eval --compare -->`. A reader knows the
date and the command; `grep -rn 'measured:' docs/` is a pre-release checklist.

**Rationale.** Unautomatable by construction, and the most valuable content here.

**Behavioural claims** — "dry_run makes no model call", "mutations answer 409 during
a reindex", "reindex loads active rows only". These are the largest drift class this
project actually suffered, and a document test cannot touch them. They are covered
by `tests/`, which is why [08-testing.md](08-testing.md) is a normative document and
not an appendix.

## Constraints

A 16 GB MacBook Pro. No local LLM. Everything on the read path runs locally, which is
what makes reading free enough to do on every turn; the judge is the only component
that leaves the machine and the only one that costs money. There is a hard monthly
ceiling enforced in code — see
[04-judge.md](04-judge.md#cost-shape) — because one runaway loop can spend a month's
budget in an hour, and by the time a human notices it is already spent.
