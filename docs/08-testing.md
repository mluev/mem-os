# Testing

This system has no single correct output. Whether a window contains a durable fact
is a judgement, and two reasonable people disagree about half the cases. So unit
tests cover plumbing only, and quality is checked by other means — four layers, in
order, because a later layer is uninterpretable while an earlier one is red.

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

Stdlib `unittest`, no pytest, entirely offline. Current counts are in
[measurements.md](measurements.md#tests).

This document was deleted at one point and restored, and the restoration is not
faithful: parts of the original strategy tested features that have since been
declined. Those parts are marked, because "we decided not to" and "we forgot" look
identical in a document six months later.

## Layer 0 — observability

Until the store can be inspected with one command, testing is guesswork.

`GET /v1/admin/stats`, `GET /v1/memories`, `GET /v1/memories/{id}/sources` and the
`/ui/` dashboard cover this. `memkit judge-runs` prints recent model calls with their
operations and reasons.

*Changed from the original:* it specified `memkit events --tail`, which depended on
an events journal that is not built
([decisions/0007](decisions/0007-no-events-journal.md)). The judge-run views serve
the same purpose for the questions that actually get asked.

## Layer 1 — plumbing

Deterministic, always green, fast. If any of this is red, nothing measured in the
layers above it means anything.

| what | where |
|---|---|
| reindex roundtrip: counts and ids survive, expired facts do not come back | `tests/test_invariants.py` |
| idempotent ingest: the same `external_id` twice leaves one message | `tests/test_invariants.py` |
| soft delete: absent from search, row intact, reversible | `tests/test_invariants.py` |
| scope isolation: a fact from another project is never returned | `tests/test_invariants.py` |
| assistant-only source is refused at the write | `tests/test_provenance.py` |
| the provider never raises: service down, prefetch returns `""` | `tests/test_hermes_provider.py` |
| credential scrubbing, one case per secret shape | `tests/test_hermes_provider.py` |
| every guarded route rejects a missing or wrong key | `tests/test_api.py` |
| every mutation answers 409 during a reindex | `tests/test_api.py` |
| `dry_run` makes no model call | `tests/test_admin_routes.py` |
| the schema migration preserves the board, the chain and every row | `tests/test_provenance.py` |

Two of these are worth their weight for a specific reason.

**The auth matrix reads its route list from the application's own schema** rather
than a list in the test. A router mounted without the key dependency is one line
away at all times, and a hand-maintained list would not cover the route that got
added yesterday.

**The dry-run tests patch the judge to raise.** Asserting "the mock was not called"
passes when the code path changes shape. Making the call explode fails loudly.

**Criterion: all green. Otherwise stop and fix this before looking at anything
else.**

## Layer 2 — extraction quality

Where the system breaks most and where breakage costs most: a bad fact cannot be
rescued by good search.

`eval/golden.py` against `eval/golden/conversations.yaml` — hand-written windows
with known answers, scored through `judge.Op.parse` so a variant cannot pass by
emitting something production would reject.

```bash
uv run python -m eval.golden --variant gemini-3.5-flash-lite:v6
```

Metrics, in priority order:

| metric | meaning |
|---|---|
| `leak` | credential values reaching the store — **any non-zero value fails the run outright** |
| `recall` | expected facts matched |
| `fp` | facts invented where the answer was "nothing" — scored separately, never averaged into recall |
| `scope` | of facts found, how many landed in the right scope |
| `imp` | how many cleared the case's importance floor, which catches the everything-is-0.6 collapse |
| `op` | right operation, and right id when declared |
| `over` | operations above the case's cap |

**Half the golden set should expect nothing.** This is the discipline everyone skips
and the one that catches memory poisoning — a model that stores something from every
window will score well on recall and fill the store with noise.

*Current gap, stated rather than hidden:* the set has 21 cases and 5 that expect
nothing, about 24% against a target of 50%. Closing it means writing more
empty-expectation cases, not relaxing the target.

*Changed from the original:* it specified matching by embedding similarity to a
reference phrasing; the implementation uses regexes
([decisions/0036](decisions/0036-content-based-eval-assertions.md)).

The golden set has also **topped out as a discriminator** — three prompt versions
tie on it while differing 2.8× on the real corpus. Treat it as a regression guard,
not a comparison instrument.

Run it on every prompt change, both versions side by side.

## Layer 3 — search quality

`eval/queries.yaml`, 47 cases grounded in the real corpus.

```bash
uv run memkit eval --compare
uv run memkit eval --target raw
```

**Use `--compare` for any raw-versus-facts claim.** A single-target run scores only
the cases that target can answer, so two single-target printouts cover different
question sets. This project published comparisons across mismatched sets for weeks,
because the harness claimed in its own docstring to hold the questions constant
while filtering them per target four lines below.

Metrics: `recall@10`, MRR, top-1 share, reject violations, mean and max tokens.
Recall saturates — ten results out of hundreds of documents — which is why MRR is
reported beside it and why MRR-per-token is what the stage-2 argument turns on
([decisions/0038](decisions/0038-stage-2-exit-gate.md)).

Assertions are regexes over returned text, never memory ids: re-extraction mints new
ids by design, so an id-pinned eval invalidates itself the first time you exercise
the operation the whole design is built around.

### The case mix, and what is missing

The original strategy prescribed a mix. Current coverage against it:

| case type | tests | target | have |
|---|---|---|---|
| direct hit | recall | 10 | ~31 |
| stale fact does not surface | forgetting, supersession | 5 | 0 |
| another project's fact | scope filtering | 5 | 7 |
| not a memory question | the right to stay silent | 5 | 0 |
| "uh huh", "go on" | degenerate queries | 3 | 0 |
| many relevant facts | adaptive output size | 2 | 0 |

Three of those six are at zero, and the gap is not cosmetic. The last two would
exercise machinery that is declined
([decisions/0029](decisions/0029-budget-tokens-not-elbow.md)) — and the honest
reading is that the machinery was declined partly because no case could show it
working. Cases first, then reconsider.

The "not a memory question" row is the most valuable missing one: it is the only
thing that would measure whether the system knows when to say nothing.

*Changed from the original:* it also prescribed an adaptivity assertion — that the
number of returned facts varies across queries and reaches zero somewhere. That
depends on the declined output machinery and on the declined similarity floor
([decisions/0028](decisions/0028-no-similarity-floor.md)), so it is not asserted.

## Layer 4 — the long run

The only layer that finds slow degradation. Layers 1–3 cannot see it, because each
run looks fine.

Run monthly and after every prompt change, and record the result with the date and
prompt version:

1. **Fact growth per 100 turns.** Must plateau. The cheapest and most revealing
   metric there is: if the active fact count grows linearly with conversation volume,
   the system is broken regardless of how green everything else is.
2. **Scope distribution.** `by_scope` in `GET /v1/admin/stats`. Everything landing in
   one scope means drift has already happened
   ([decisions/0039](decisions/0039-relabel-v4-scoped-facts.md)).
3. **Near-duplicate share.** Active same-type pairs above the consolidation
   threshold. A rising share means the consolidator is not keeping up — or is blocked,
   which is currently more likely
   ([decisions/0032](decisions/0032-cluster-connected-components.md)).
4. **Contradictions.** Pairs above ~0.85 that assert opposite things. Needs a model
   call and a human read.
5. **Provenance.** `by_source_role` in `GET /v1/admin/stats`. **`assistant` should be
   0** for extracted facts. A non-zero and rising count means model-authored text is
   accumulating as remembered fact — the failure
   [decisions/0006](decisions/0006-source-role-and-may-write.md) exists to make
   visible. This metric survived the restoration intact, because the column it needs
   was restored with it.

Expect the first run to look bad. That is the layer working.

## What not to do

**Do not mock the judge in layer 2.** Mocking belongs in layer 1. A mocked judge
measures the plumbing around a decision, not the decision.

**Do not assert exact fact strings.** The model paraphrases, the test goes red for no
real reason, and eventually someone disables it. Regexes and importance floors, not
equality.

**Do not start at layer 4.** It is the most interesting and the most useless while
layer 1 is red — you cannot tell degradation from a bug.

**Do not count "it answered" as a test.** A system remembering nonsense answers just
as confidently as one remembering the truth.

**Do not let a test reach a paid API.** The first run of the HTTP suite made a real
billed call, because the credential settings carry a `validation_alias` and the
obvious way to blank them silently does nothing. `tests/httpharness.py` now asserts
on every setUp that no credential survived. A test that spends money is worse than a
test that fails.

## Known gaps

Recorded rather than left to be discovered:

- `src/memkit/cli.py` has no tests. Nine subcommands, including `install-hermes`,
  which writes into `$HERMES_HOME`.
- The transcript importer's **classifier** is well covered (28 cases); the file walk
  around it is not.
- The provider response parsers are exercised only through mocks. No test feeds a
  realistic Anthropic or Gemini tool-use response through the real parser.
- `web/` has two logic tests and no component tests. There is no jsdom and no
  testing-library installed, so rendering tests are not currently possible.
- Nothing detects drift between `web/src/api/schema.d.ts` and the live OpenAPI
  schema, even though the former is generated from the latter.
- There is no CI. The suite is run by hand, and it needs MPS and a local Qdrant for
  the eval layers, neither of which a hosted runner has.
