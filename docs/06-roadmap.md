# Roadmap

Stages, their exit criteria, and what is actually done. State is tracked **per
item**, not per stage: the previous version of this document called stage 6 "not
started" while listing one of its four items as finished, which is how a roadmap
stops being usable.

Current counts are in [measurements.md](measurements.md); nothing here restates
them.

## Stage 0 — the hardware gate — done

Embedding latency under 100 ms on MPS, 1024 dimensions. `memkit bench` is the gate
and exits non-zero on a wrong dimension, because a silent model swap would make
every stored vector incomparable and nothing else would notice.

## Stage 1 — foundation — done

Ingest, the transcript importer, raw-turn indexing, reindex-from-truth, and the eval
harness. This stage's output is the baseline everything later is measured against:
semantic search over the user's own messages.

## Stage 2 — the extractor — done, with the gate restated

Judge, gate, cost ceiling, window abandonment, provenance guard. The whole imported
history has been processed.

**The exit criterion, as originally written:** the eval must beat stage 1.

**The criterion actually in force:** comparable MRR inside a 600–1,000-token budget,
which raw turns cannot meet — their mean answer alone is four times the ceiling.

That substitution is not a tidy-up. Taken literally the original gate was **not
met**, and stage 2 was advanced anyway. The full argument, the numbers, and a
recorded dissent are at
[decisions/0038](decisions/0038-stage-2-exit-gate.md). It is restated here rather
than left standing as written, because a gate nobody applies teaches everyone that
the gates are decorative — but the substitution itself is on the record.

## Stage 3 — retrieval — done

Composite score, scope filtering, dedup, budget fill. Details in
[05-retrieval.md](05-retrieval.md).

Two designs from this stage were declined after measurement rather than built: the
similarity floor ([decisions/0028](decisions/0028-no-similarity-floor.md)) and the
elbow-cut/modes machinery
([decisions/0029](decisions/0029-budget-tokens-not-elbow.md)). Both have stated
conditions for reopening.

## Stage 4 — the nightly consolidator — done

Expiry, demotion, merging, scheduled at 04:00 via launchd. Two steps were added
during implementation that no earlier document had specified, and both were
necessary: validity expiry (before it, date-expired facts were being served as live)
and importance demotion for facts nothing retrieves.

## Stage 5 — the Hermes adapter — done

`MemoryProvider` plugin, verified end to end: a fact stated in one session surfaced
in another agent's session. See [07-hermes-adapter.md](07-hermes-adapter.md).

## Stage 6 — the local dashboard — done

Overview, memories with provenance, search scoring, judge runs, sessions and
messages, operations, and the task board. Mutations go through the API, which means
the dashboard cannot do anything an agent could not.

## Not started

Each of these is genuinely untouched, which is the right state for all four.

| item | state |
|---|---|
| BM25 hybrid retrieval | deferred with a measured trigger — [decisions/0050](decisions/0050-bm25-deferred.md) |
| a second user | `owner_id` is already everywhere, including the Qdrant payload index; only authentication is missing |
| a separate collection for documentation retrieval | not needed; the boundary in [01-architecture.md](01-architecture.md) exists so documentation cannot leak into memory results |
| CI | the eval layers need MPS and a local Qdrant, neither of which a hosted runner has |

## Open work

Not code, and not blocked on anything.

**Legacy over-scoped facts.** Roughly two-thirds of active facts are
project-scoped, and by inspection a meaningful share of those are facts about the
person that will only surface if the right repository is named. Reclassification is
a manual review with a tool ready to assist it
([decisions/0039](decisions/0039-relabel-v4-scoped-facts.md)). Facts extracted under
the current prompt do not have the problem, so this is a backlog rather than a leak.

**Eval case-mix gaps.** Three of the six prescribed case types have zero coverage,
including the one that would measure whether the system knows when to say nothing.
Listed in [08-testing.md](08-testing.md#the-case-mix-and-what-is-missing).

**Golden-set composition.** About a quarter of cases expect nothing, against a
target of half. The empty-expectation cases are the ones that catch memory
poisoning.

## What not to build

Recorded so that each stays decided rather than being re-proposed.

- **A local LLM as the judge.** 16 GB is already committed to the embedder and
  Qdrant, and the judge is called rarely enough that the API cost is under a dollar
  a month.
- **A graph memory.** The retrieval problem here is ranking, not traversal.
- **Documentation or code corpora in the memory collections.** Different scoring,
  different lifecycle; a separate system if it is wanted at all.
- **mem0 or a similar library as the core.** The interesting parts of this project
  are the extraction gate, the scope model and the provenance guard, all of which
  would have to be reimplemented on top of any such library anyway.
