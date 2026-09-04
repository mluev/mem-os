# 0070 — Routing through a numbered ENTITIES block, behind the integer remap

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      tests/test_extract_v4.py, tests/test_prompts.py
    Code:          src/memkit/prompts.py (V9), src/memkit/judge.py (extract, render_entities), src/memkit/entities.py (for_prompt)
    Contract:      ../04-judge.md#routing

## Decision

Prompt v9 is v8 plus an `ENTITIES` block: the entities the speaker can see, numbered from one, each labelled by kind and carrying the aliases people actually say. Order is fixed — the speaker, the team, then their projects and products, then teammates — and the list is capped, so the tail that gets dropped is the least likely to be needed.

Operations return `scope` and `subject` as **integers into that block**. Names and ids are never accepted. A number outside the block is dropped as `unknown_entity` and counted as a rejection, exactly as a fabricated candidate id is. The map is recorded with the judge run, so a stored fact can be explained afterwards.

For a person the model saw named but could not find in the block, it returns `subject_name` verbatim. The service tries an exact alias lookup; if that fails, the fact is written to the speaker's private scope with no subject, and a `needs_attention` row asks a human who was meant. Resolving that item links the memory to the entity **and teaches the alias**, so the same name resolves by itself next time.

## Alternatives and why not

**Let the model return a slug or a uuid.** A uuid shown to an LLM comes back subtly mutated often enough to be a failure class — the reason candidate ids were already remapped to integers in [0054](0054-semantic-candidates-with-integer-remap.md). A slug is worse in a specific way: it is *plausible*. `alex` looks like a real answer whether or not it exists, so a fabricated one has to be detected by a lookup that will sometimes succeed against the wrong entity. An integer outside a list of eleven is provably fabricated, and can be rejected with a clean conscience.

**Route in code from the fact's text.** Match names against the alias table after extraction and route on the hit. This loses the only thing the model has that the code does not: it has just read the sentence. "Alex mentioned that Саша prefers dark mode" contains two names and one subject, and a text match finds both. Routing is a reading-comprehension task, which is why it is asked of the reader.

**Fuzzy alias matching.** Rejected outright. A fuzzy match routes a fact about one person into another person's profile, which is worse than not routing it at all: the unrouted fact is merely private, the misrouted one is wrong about somebody, in a place they will read it. Alias resolution is exact on the case-folded form, and aliases are globally unique for the same reason — if two entities answered to "Саша", every fact about either would be a guess.

**Drop the fact when the name cannot be placed.** It was stated, so it is evidence, and discarding it makes the extractor lossy in the case most likely to matter (a new colleague, a nickname nobody has registered). Keeping it private and unattributed preserves it without asserting anything about a person, and the review item is how it gets placed.

**Show the model every entity.** The block is capped because it is billed per call and because a long list of strangers dilutes the ordering the routing rules depend on. The order is the mitigation: the entities a speaker's facts are most likely about are the ones that survive the cap.

## Consequences

Extraction now needs the speaker's entity list, which is one bounded query per window, and the prompt grew by that block. Routing failures are visible rather than silent: `unknown_entity`, `scope_not_allowed` and `target_scope_mismatch` are per-op rejection reasons in the job result, and `unresolved_mentions` is a counter next to them. A named scope the speaker cannot write to is refused rather than redirected, because a fact written to the wrong scope is either a leak or a loss.
