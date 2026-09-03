# Extractor prompts: a lab notebook

Dated entries, appended and not edited. Every number here is **frozen** — it
measured a prompt version that may no longer be in production, on a corpus that has
since grown. Nothing here should be cited as current; that is
[measurements.md](../measurements.md)'s job.

The notebook exists because the useful output of these experiments was not the
winning variant. It was the four hypotheses that turned out to be wrong, and one
defect that invalidated three weeks of comparisons.

Current state, generated from the code:

<!-- generated:prompt-versions -->
| | |
|---|---|
| registry | `v7`, `v8` |
| active extractor prompt | `v8` |
| consolidator prompt | `c2` |
| stamped on new facts | `v8` |
| default judge model | `gemini-3.5-flash-lite` |
<!-- /generated:prompt-versions -->

Every fact stores its `extraction_version`, so versions coexist in one database and
can be compared rather than taken on faith.

## 2026-07-29 — the measurements were not measuring production

Everything recorded before this date was measured on something other than what was
running.

`judge.py` held its own copy of the prompt — verbatim v2 plus a `task_status`
block — while stamping every extracted fact with `prompts.DEFAULT_VERSION`, which by
then said `"v4"`. `prompts.render()` was called only by the two eval scripts. So
production ran v2 and labelled its output v4, and v3, v4 and v5 had never processed
a real message: no "where this conversation happened" block, no "what to look for"
rule (which is the actual recall driver), no importance anchors. `session_date` was
discarded too, so "last month" resolved against today rather than against the day
the conversation happened.

Fixed by making `judge.build_prompt()` the only path to prompt text, pinned by
`test_production_prompt_is_the_active_registry_version`. Twelve judge runs and two
facts mislabelled `v4` were re-stamped `v2`, which is what they were.

**The bench numbers below remain valid as comparisons of versions against each
other. None of them described production before this date.**

The lesson is not "be careful with constants". It is that a value which *names* a
behaviour must be derived from the behaviour, not maintained alongside it. That is
now [decisions/0016](../decisions/0016-one-home-for-prompt-text.md), and it is the
same failure the whole documentation reconciliation was about, one layer down.

## Two benches, and why both

`eval/experiment.py` runs the same real windows through several model×prompt
combinations and **writes nothing** to the store. It shows what a variant *did*.

`eval/golden.py` with `eval/golden/conversations.yaml` runs hand-written windows
with known answers. It shows whether a variant was *right*. Without it, comparing
versions is looking at output and forming an impression.

```bash
uv run python -m eval.golden --variant gemini-3.5-flash-lite:v6
uv run python -m eval.experiment --windows 20 --variant gemini-3.5-flash-lite:v6
```

The golden set validates through `judge.Op.parse` — the production gate — rather
than a bespoke parser, so a variant cannot pass the bench by emitting something the
real pipeline would reject.

## v1 → v2: the window was the problem, not the prompt

v1 on Claude Sonnet 5 produced facts with a median length of 354 characters and a
maximum of **2,161** — an entire session changelog stored as one memory. All 16
facts came out `scope=project`.

The cause was not the instructions. It was that assistant turns are 2,000-character
walls, and the model was summarising them.

v2 added a length cap, changelog-versus-fact examples, and truncation of assistant
turns to 220 characters. Median length fell to 103, maximum to 185, and
`scope=user` appeared for the first time.

## v2 → v3: naming the project primes the model (refuted)

v3 named the current project in the prompt and added a profile block of what was
already known about the person, to avoid repetition.

Both changes backfired. Naming the project primed the model to call everything
project-scoped: a pnpm preference and the user's own GitHub login were both filed as
`scope=project`, and identity importance dropped to 0.5. The "don't repeat what you
know" block acted as a silencer — **0% user facts** on the real corpus.

A block intended to prevent duplication instead prevented extraction. Worth
remembering when adding any instruction that tells the model what not to say.

## v3 → v4: keep the good half

v2's base, plus v3's "what to look for" block and importance anchors, plus an
explicit anti-priming warning. Profile block removed.

On the golden set of the time (15 cases, 12 expected facts), v2, v4 and v5 all
scored 92% recall with zero false positives, zero credential leaks, 8/8 on scope,
2/2 on importance and 1/1 on UPDATE. On 20 real windows, v4 found twice as many
facts as v2 (14 against 7).

**A metric trap, recorded because it nearly cost the right answer.** v4 was almost
rejected on `scope=user` *share* — 21% against v2's 43% — when both had found
exactly 3 user facts in absolute terms. v4 simply found more project facts too. The
bench now prints absolute counts alongside shares.

## v5: removing the project mention does not cure priming (refuted)

v5 dropped the project name entirely. The user share was unchanged (20% against
21%) and recall was the worst of the three. Priming was not coming from the mention.

## 2026-07-29 — the full corpus disagreed with the bench

Running v4 over everything: 247 calls, $0.50, one error, 88 active facts.

The 20-window bench had been unrepresentative in almost every respect:

| | 20-window bench | full corpus |
|---|---|---|
| facts per window | 0.70 | **0.33** |
| user facts | 3 | **21** |
| median fact length | 84 | 128 |
| distinct importance values | — | 6, spanning 0.4–0.9 |

Facts over the 200-character cap: 3 of 62.

Scope priming was only partly cured: 41 of 62 facts were `scope=project` against 21
`scope=user`, so about a third of the store was reachable without naming a project.
By inspection roughly 17 of the 41 read as facts about the person rather than the
codebase — which is now
[decisions/0039](../decisions/0039-relabel-v4-scoped-facts.md).

The language rule was ignored about 70% of the time: 20% of input was Russian
against 6% of facts. Retrieval was unaffected — a Russian query reached the matching
English fact at rank 1 — which is what led to dropping the rule
([decisions/0015](../decisions/0015-no-language-rule.md)).

## v6: three hypotheses, two refuted

**(1) Do not trust the model's `scope`.** Added a required boolean
`holds_in_other_repos` and a one-way project→user correction in `Op.parse`, and
replaced rule 5 with it. **Recall collapsed fivefold** — 0.10 facts per window
against v4's 0.50, with 18 of 20 windows empty. Restoring rule 5 alongside the new
field got 0.20, still three times worse.

The cause was not the new question but what the replacement deleted. Rule 5 also
*pushes* extraction — "a window usually contains BOTH… look for both" — and that
clause is the recall driver. The travel test now sits in the schema field
description and appends to rule 5 rather than replacing it.

**(2) The travel-test wording suppresses extraction.** Removing it from the prompt
text levelled recall (0.35 against 0.35) but produced zero user facts. Refuted:
the wording was not the problem.

**(3) The drift is in the phrasing, not the label.** Correct. v4's rule 2 said
"never write 'this project' — name the project", which forced the repository name
into every fact, so the model's own sentence looked repository-bound and it labelled
the scope to match. **Rule 2 was fighting rule 5.** v6 makes the repository naming
conditional on the fact actually being about the repository.

Measured on 51 windows, paired, two pooled runs:

| | facts | per window | user | project | task | user share |
|---|---|---|---|---|---|---|
| v4 | 27 | 0.26 | 7 | 18 | 2 | 26% |
| **v6** | 24 | 0.24 | **13** | 11 | 0 | **54%** |

Slightly fewer facts, twice the user share — which is the trade that matters,
because a user-scoped fact is reachable from every project and a project-scoped one
is reachable from one.

**Run-to-run variance, stated because it undermines every single-run comparison
above.** v4 produced 0.24, 0.27, 0.35, 0.50 and 0.60 facts per window on the same
bench and the same corpus. Run 1 of v6 showed 69% user facts; the repeat showed 36%.
Report the pooled sum, never a single run. The bench ceiling is 51 windows because
`pick_samples` takes one window per session.

## Open questions

**Mixed windows under-extract.** The golden case `mixed-user-and-project` contains
two facts, and every variant and every model finds the same single one. Nothing
tried has moved it.

**The golden set has topped out as a discriminator.** v2, v4 and v5 tie on it while
differing 2.8× on the real corpus. It is now a regression guard rather than a
comparison instrument — it catches a variant that breaks something, not one that is
better. It has 21 cases and 5 that expect nothing (~24%); the original testing
strategy asked for half the set to expect nothing, and that gap is tracked in
[08-testing.md](../08-testing.md).

**Prices are unverified for every model except the default.** Flagged as
`price_unverified` in `judge.MODELS`. One run overstated its cost eighteenfold by
billing an unknown model at the most expensive known rate — the correct direction to
be wrong in, and still wrong.
