# Retrieval

The hardest part of the system, and the part where being wrong is least visible: a
bad fact announces itself, but a good fact that never surfaces looks exactly like a
system with nothing to say.

Reading is local and free — no model call — which is what makes it affordable on
every turn.

## The score

Each candidate gets a composite score:

```python
score = (W_SIMILARITY * similarity
         + W_IMPORTANCE * importance
         + W_RECENCY    * recency
         + W_SCOPE      * scope_boost)
```

The literals are not written here on purpose; they are generated from the module so
this document cannot disagree with the code:

<!-- generated:retrieval-weights -->
| term | weight | constant |
|---|---|---|
| similarity | 0.55 | `retrieval.W_SIMILARITY` |
| importance | 0.20 | `retrieval.W_IMPORTANCE` |
| recency | 0.15 | `retrieval.W_RECENCY` |
| scope_boost | 0.10 | `retrieval.W_SCOPE` |

The four weights sum to 1.00.

| parameter | value | constant |
|---|---|---|
| overfetch | 50 | `retrieval.OVERFETCH` |
| dedup cosine | 0.90 | `retrieval.DEDUP_COSINE`, overridable with `MEMKIT_DEDUP_COSINE` |
| characters per token | 3 | `retrieval.CHARS_PER_TOKEN` |
<!-- /generated:retrieval-weights -->

These are starting values. They are tuned against the eval
([08-testing.md](08-testing.md)), never by feel — a weight adjusted because a
single query looked wrong is how a ranking function stops being explainable.

### Similarity

Cosine, from Qdrant, over BGE-M3 vectors. Embeddings are L2-normalised so the dot
product *is* the cosine.

Retrieval is **dense only**. There is no BM25, no lexical arm and no fusion. Both
collections declare a sparse slot that nothing writes to, purely so that enabling
hybrid search later does not require recreating the collections
([decisions/0050](decisions/0050-bm25-deferred.md)).

### Recency

`exp(-age_days / tau[type])`, with age measured from **`updated_at`**, not
`created_at`. A fact the user restates today is fresh again; the alternative would
make a five-year-old confirmed preference decay identically to a forgotten one.

<!-- generated:retrieval-tau -->
```python
# Recency half-life per type, in days. retrieval.TAU
TAU = {
    "preference": 540,
    "fact":       900,
    "skill":      270,
    "relation":   270,
    "project":    180,
    "decision":   180,
    "task":       2,
}
TAU_DEFAULT = 180  # unknown type
```
<!-- /generated:retrieval-tau -->

The spread is the point. A `fact` — where someone lives, what they are called —
should survive a year of silence. A `task` should be almost gone in days, because a
stale task is worse than no task: it invites an agent to act on something already
finished. `preference` sits in between, on the reasoning that people change tools
faster than they change cities.

### Scope

The scope boost is not really a boost. It returns `None` for a fact that must not be
returned at all, and a filtered fact is **discarded, not down-weighted**:

| scope | key | result |
|---|---|---|
| `user` | — | 0.0, always admitted |
| `project` | matches the request | 0.5 |
| `project` | different project | **discarded** |
| `project` | no key | **discarded** |
| `task` | no key | 1.0, always admitted |
| `task` | matches the current task | 1.0 |
| `task` | different task | **discarded** |

Down-weighting would be wrong rather than merely weaker. On a thin corpus a
down-weighted foreign fact still reaches the top of a short result list, and "the
auth module lives in `app/auth`" surfacing while you work in a different repository
is not a slightly worse answer — it is a confidently wrong one.

The same rule is applied twice: once as a Qdrant filter, so foreign facts never
leave the database, and once in the rescoring pass as a belt-and-braces check. An
unkeyed `project` fact is a bug at write time; making it unreachable means the bug
costs nothing until it is fixed.

## Dedup

A greedy top-down pass: for each candidate, if it is at least as similar as the
threshold to something already kept, drop it and record what beat it. Items with no
vector are kept unconditionally — the absence of a vector is an indexing problem,
and dropping the fact would hide it.

The threshold is 0.90, and it is probably slightly too strict. That is argued, with
the measurements, at
[decisions/0030](decisions/0030-dedup-stays-at-0.90.md).

Dedup needs the vectors back from Qdrant, which requires asking for them:
`with_vectors=True`. Qdrant does not return them by default, and without that flag
dedup silently does nothing — the comparison runs against `None` for every item and
never fires. This cost a working feature once.

## Filling the budget

The caller supplies `budget_tokens` (default 800) and `limit` (default 30). Results
are added in descending score until the next one does not fit. An item too large for
the remaining space is **skipped, not terminal** — one verbose fact should not
truncate everything below it.

Tokens are estimated as `len(text) // 3`, not `// 4`. Cyrillic tokenises denser than
English, and the corpus is mixed, so the usual four-characters-per-token rule
underestimates by enough to overflow a budget that looked comfortable.

Aim for 600–1,000 tokens of memory per request. Above that, memory starts competing
with the thing the agent is actually doing.

There is no elbow detection, no `mode` parameter and no separate `max_tokens`
ceiling. All three were designed and are declined, with the reasoning and the
conditions for reopening, at
[decisions/0029](decisions/0029-budget-tokens-not-elbow.md).

## What is not filtered

There is no minimum-similarity floor. Vector search returns `k` results however
distant they are, so a floor sounds obviously right; measured, only the most timid
threshold was quality-neutral and it saved 8% of tokens. See
[decisions/0028](decisions/0028-no-similarity-floor.md).

An empty result is still a correct and reachable answer — it just arrives through
scope filtering and the budget rather than through a distance cutoff.

## Retrieval feedback

Every returned fact gets `last_retrieved_at` set and `retrieval_count` incremented.
Those two columns are what the nightly consolidator uses to demote facts nothing
ever asks for ([04-judge.md](04-judge.md)), and they are the cheapest available
signal about which facts are dead weight.

Note that this makes reading a write. It is a deliberate cost: without it there is
no way to distinguish a fact that matters from one that has never been used since it
was stored.

## Explaining a result

`POST /v1/admin/search-preview` returns the same ranking with every component
exposed — similarity, importance, recency, scope boost, the final score, and three
separate lists of what was dropped and why: by scope, by dedup, by budget. It also
reports the live weights and half-lives, so a surprising result can be diagnosed
without reading the source.

This is the endpoint to reach for when a query returns something baffling. "Why did
that surface?" is answerable; "why did *this* not?" needs the `dropped_scope` list,
which is why the preview endpoint runs a second unfiltered query to populate it.
