# What Supermemory does that Mem OS did not (2026-09-29)

A comparison with [Supermemory](https://github.com/supermemoryai/supermemory),
whose engine reports state-of-the-art results on LongMemEval (~85% overall,
strongest on temporal reasoning and multi-session questions) and LoCoMo. The
engine itself is closed; this reads what is public.

## Sources

Read directly:

- `supermemoryai/supermemory`: the concept docs (`apps/docs/concepts/*`: how it
  works, graph memory, memory vs RAG, SuperRAG, user profiles, rules,
  customisation), the recall and ingestion API docs, the agent skill's
  architecture reference, and `packages/validation/schemas.ts`, which has the
  memory row: `version`, `isLatest`, `parentMemoryId`, `rootMemoryId`,
  `memoryRelations` (`updates | extends | derives`), `sourceCount`,
  `isInference`, `isForgotten`, `isStatic`, `forgetAfter`, `forgetReason`.
- `supermemoryai/memorybench`: the benchmark harness, and in particular the
  Supermemory provider's ingestion (whole sessions, prefixed with their date)
  and answer prompt, which shows results carry
  `temporalContext.documentDate` and `temporalContext.eventDate[]` plus the
  source chunks behind each memory.
- `supermemoryai/claude-supermemory`: the Claude Code plugin (profile at
  session start, reasoned recall per prompt, capture at stop).

Not reachable from the environment this was written in: supermemory.ai
(including the LongMemEval research page), X, dhravya.dev and arXiv. Their
LongMemEval write-up is summarised by search snippets as "atomic memories,
relational versioning, temporal metadata and source chunks", which matches
what the code above shows.

## The comparison

| Supermemory | Mem OS before | Now |
|---|---|---|
| Atomic, contextual memories; one input yields many facts | Atomic, self-contained, cited | Same, and v11 asks for one claim per operation with every reference resolved |
| `documentDate` and `eventDate[]` on every memory | Relative dates resolved into text only | `document_date` and `event_dates` with an indexed interval (0075) |
| Episodes kept, decaying unless significant; `forgetAfter` for temporary facts | Refused at the write | `episode` kind, decay at read time, `valid_until` for natural ends (0075, 0077) |
| `updates` with `isLatest`, `extends`, `derives` | In-place revisions only | Supersede vs correct, `memory_relations`, history on search (0076) |
| Inferences flagged `isInference`, down-weighted until reviewed | None | Dreaming writes pending inferences with `derives` edges, penalised until confirmed (0078) |
| "Dreaming" groups coherent units before learning | Ten-message windows | Windows stay; dreaming links and infers across them per scope |
| `sourceCount`; preferences strengthen with repetition | Evidence linked, not counted | `source_count` per session, a ranking and profile signal |
| Search on memories, answer from source chunks | Minimal cited span | `source_context_chars` returns the passage around each span |
| Query rewriting, reranking, related memories, forgotten opt-in | Fusion + optional LLM rerank | Rewrites fused by rank, local cross-encoder, `include_related` (0079) |
| Forget-matching with dry run and id binding | Archive by id | `POST /v1/memories/forget` (0080) |
| Static and dynamic profile | Five kind-based blocks | Static traits of any kind first; recent block ordered by time |
| MemoryBench: LoCoMo, LongMemEval, ConvoMem; MemScore | 47 internal cases | `eval/bench` with MemScore (0081) |

## What was deliberately not copied

- **Model-authored text as evidence.** Supermemory learns from whatever it is
  sent. Here only user words can support a memory (decisions/0006); an
  inference is labelled as one and never becomes a premise. This costs
  LongMemEval's assistant-recall category and is kept on purpose.
- **Container tags as the only boundary.** Scopes, subjects and roles stay the
  authorization model; every new edge and every inference stays inside one
  scope.
- **Metadata filters as the tenancy mechanism.** Supermemory recommends a
  container per permission boundary and metadata inside it; Mem OS already has
  scopes for the first and the JSON filter algebra for the second.
- **Connectors and multimodal ingestion.** Out of scope for a team memory
  service (see the roadmap).

## What remains to prove

Nothing here is measured yet. The new weights, the v11 prompt and dreaming are
reasoned from the comparison; `python -m eval.bench` against a deployment with
a judge configured is the measurement that keeps or changes them. The rows to
fill are in [measurements](../measurements.md#to-be-re-measured).
