# Supermemory, round two: the founder's articles, v5, and memorybench (2026-10-19)

The [first comparison](2026-09-29-supermemory.md) built most of what Supermemory's
public code showed — two dates, supersession, a same-scope graph, dreaming,
policy v2, rewrites, a cross-encoder, forget-matching and a LoCoMo/LongMemEval
harness — and measured none of it. This round reads what was out of reach then
(Dhravya Shah's own articles) and what changed since (Supermemory's v5 API and
memorybench's protocol fix), and asks what is still worth taking.

## Sources

**Not readable from this environment:** x.com, supermemory.ai, dhravya.dev,
hraness.com, runtimewire.com and archive.org were blocked by its network policy,
as in September. The articles below are reconstructed from search-engine
extracts and from pages that quote them; treat every summary as second-hand.

**Articles reconstructed** (all by Dhravya Shah unless noted):

- *I reverse-engineered Instinct's memory* (X article, 2026-09-20) and the blog
  teardown of the same date; the companion post *markdown vs @supermemory*.
- *Introducing Dynamic Dreaming* (blog, 2026-05-25).
- *Solving the precision-recall tradeoff: search result aggregation* (blog,
  2026-04).
- *We broke the frontier in agent memory (a parody)* — the ASMR post (2026-03).
- *dear reader, we just made supermemory insanely cheap: the Context Cloud*
  (X article, 2026-05-18).
- *Architecting a brain-inspired memory engine* (blog, 2025-06-05).
- *Jev changes a lot in memory & context engineering* (blog, 2026-09-24).
- The LongMemEval research page, *Supermemory vs Mem0*, the Codex plugin
  announcement (2026-05-12) and the refocus on the memory API (2026-09-10).

**Read directly** (raw.githubusercontent.com): `supermemoryai/supermemory`
(docs for the v5 API, dreaming, search, profiles and buckets, forgetting,
scoped keys, self-hosting, billing; the MCP server), `claude-supermemory`,
`codex-supermemory`, `opencode-supermemory`, `memorybench` (PR #96, merged
2026-10-19, and PR #97), the third-party `Bilal140202/openmemory` deep dive, and
`deepakkrsoni/voice-instinct`, which rebuilt Instinct's design from the
teardown. The engine itself is closed: the self-hosted server is a binary
"built from a separate, non-public codebase".

## What the numbers actually say

Supermemory's own harness, once its protocol was fixed (memorybench #96: one
container per conversation, Mem0-paper prompts, a search limit of 30,
adversarial questions out of the headline, waiting for memory formation),
scores Supermemory **68.8%** on LoCoMo with gpt-4o-mini, and **76.6%** on a
308-question re-ingested subset; the old harness said 52.8%. For reference, the
PR quotes Mem0's paper: Mem0 66.9%, Zep 66.0%. The "~99% on LongMemEval" was a
deliberate parody — a question counted as answered if any of eight prompt
variants got it right. The published LongMemEval-S figures (85% overall, 81.6%
with gpt-4o) are strongest on single-session-assistant (100), knowledge update
(99) and temporal reasoning (91).

So the lead is narrower than the marketing, and it is concentrated where Mem OS
deliberately refused to go: questions about what the assistant said.

## What changed in Supermemory since September

**v5 (2026-10-06; v3/v4 shut down 2026-12-31) moved away from teams.** A
document lives in exactly one namespace; reading across namespaces is one call
per namespace merged by the client. Direct memory writes and version updates
were removed: everything is ingested as documents. Scoped keys can cover several
namespaces with expiry and a rate limit, and Scale-plan members can be
restricted read/write per namespace — but the memory model has no notion of a
fact about a teammate, of attribution, or of a review queue. Mem OS's single
search across every scope a caller can read, with scope and subject on every
result, is the part Supermemory does not have. It stays.

**Searchable versus formed.** `system.status` reaches `done` when chunks are
indexed; `system.dreamingStatus` reaches `done` when memories have formed,
"minutes" later. memorybench now waits on the second.

**Dreaming is dynamic by default.** "When you go quiet, or when enough new
context has piled up, Supermemory will now enter a dream cycle on its own. No
cron job, no fixed timer." A dream reconsolidates, merges fragments, reweights
old facts and tempers over-confident ones; "if it can't show its work, it
doesn't get to claim the thought". Unprocessed content stays searchable through
hybrid retrieval meanwhile.

**Forgetting is dry run, then ids.** Semantic forget requires `dryRun`; the
documented flow is to review the matches and delete them by id "to avoid
selection drift", and the MCP server switched from LLM matching to ids
(#1820).

**Search defaults** are now `searchMode=hybrid`, `threshold=0.3`, `limit=10`,
`rerank: none | order | aggregate` (order adds ~100 ms; aggregate merges
overlapping results into one slot), `rewriteQuery=false`, and
`include.{documents, related, forgotten}`.

**Profiles** take no query: static, dynamic (each entry dated `[YYYY-MM-DD]`,
older ones condensed into `aggregated_*` summaries) and topic buckets assigned
by a classifier, with org-level and add-only namespace buckets.

**Extraction steering**: an org-wide `organizationalContext` and a per-namespace
`supportingContext` (≤ 1,500 characters) are injected into the extraction prompt.

**Client capture** (claude-supermemory): the delta since the last captured
entry, user and assistant text, tools only when listed, credentials redacted,
`<private>…</private>` removed (codex plugin); recall injects five results of
300 characters at similarity ≥ 0.55 with a 4 s fail-open timeout.

## What the articles add

- **Assistant info is evidence.** ASMR's readers extracted "across six vectors:
  personal information, preferences, events, temporal data, updates, assistant
  info". Whole sessions are ingested, assistant turns included, which is where
  the single-session-assistant score comes from.
- **Sessions, not windows.** The LongMemEval run ingests each session whole and
  decomposes it into semantic blocks whose atomic memories resolve references
  within the block, keeping the block as the source chunk.
- **Instinct's design** (the teardown): git-tracked markdown files with aliases,
  found with grep; a ~4,250-token profile and a ~10k-token recap at session
  start; one reconciliation pass a day that replaces wrong facts with dated
  corrections. Shah's own scorecard: single facts, recency, updates and
  abstention pass; multi-hop across sessions is weak; forgetting is "not
  automatic". His counter-design is an "instant file" assembled per request —
  the whole history, forgotten facts removed, related facts included — which is
  what search with history and related memories already returns here.
- **Aggregation** (April): reranking fixes precision but a result limit caps
  recall; a slot that synthesises several overlapping memories answers a
  two-part question within the same limit. 97% Recall@20 on LongMemEval-S.
- **The harness decides when memory helps**, not the model ("models are very
  bad at deciding when some memory should be helpful"), and writes happen off
  the hot path.
- **Cost**: bill and process only unique tokens; report MemScore — accuracy,
  latency and context tokens together — rather than accuracy alone.

## What this round built

| Supermemory | Mem OS before | Now |
|---|---|---|
| Assistant turns are evidence | Refused at the write (0006) | Prompt v12: assistant info, labelled `assistant`, pending, penalised, never revises a stated fact (0082) |
| Sessions ingested whole | Non-overlapping 10-message windows | v12 shows the four messages before the window, uncitable (0083) |
| `rerank`, `searchMode` per request; server defaults | `neutral-v1` hard-coded | `MEMKIT_DEFAULT_POLICY`; `core-retrieval-v3` trusts assistant memories and passages (0084) |
| Dynamic dreaming; `dreamingStatus` | Dream after every extraction | `MEMKIT_DREAMING=dynamic`; `caught_up`; dream supersessions listed for review; a daily maintenance pass (0085) |
| Forget: dry run, then ids | Unverified query matches applied | 409 unless verified; apply by ids (0086) |
| `<private>` removed before capture | — | Removed before persistence and egress; injected memory blocks never stored as evidence (0087) |
| memorybench protocol fix | Shared team scope, no reuse, unpaired | Own-scope search, `--source-run`, stratified `--sample`, paired `compare`, `--dream`, spend (0088) |
| ~100 ms rerank, ~50 ms profile, p95 published | One latency number | Per-stage and per-policy p50/p95; rerank once after fusion; profile timing |

## Deliberately not taken, or not yet

- **Namespaces as the only boundary, and no direct writes.** v5's direction is
  the opposite of a team memory with attribution and review.
- **Model-authored text as the user's evidence.** The stance is adopted for what
  the assistant said, written as such; it is never a premise for dreaming, never
  counts as a second mention, and cannot overwrite what a person stated. The
  self-reinforcement loop 0006 was written against stays broken by
  construction rather than by a prompt request.
- **Search result aggregation** — deferred. Mem OS's limit is a token budget as
  well as a count, so the gain is smaller; the design (group the top results by
  `extends`/`updates` edges and same-subject near-duplicates, one slot per
  group) waits for the benchmark to show multi-part questions failing on the
  limit.
- **Per-scope extraction guidance** (their `supportingContext`) — deferred to a
  prompt v13 so v12 measures one idea at a time; it would be a scoped policy row
  rendered into the prompt.
- **Scoped, expiring, read-only API keys** — deferred: they need a schema v4.
- **Buckets** — the five profile blocks are already topic-shaped for a team
  (who you are, how you work, the team's rules, this project, what changed).
- **A freshness tail** (searching messages not yet extracted) — user turns are
  already raw-indexed on arrival; `include_raw` returns them.
- **ASMR-style agentic answering** — it measures the answering harness, not the
  memory.

## What remains to prove

As in September, nothing above is measured. Every new behaviour is opt-in, and
[measurements](../measurements.md#to-be-re-measured) lists the runs that decide
it, with the rule each must pass to become a default. Two things block them in
this environment: no `GEMINI_API_KEY`, and `huggingface.co` (the embedding model
and LongMemEval) is not reachable.
