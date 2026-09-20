# 0063 — A fact about a teammate goes straight into the team scope

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      tests/test_extract_v4.py (a fact about a teammate becomes a team fact about them)
    Code:          src/memkit/extract.py (_resolve_routing), src/memkit/prompts.py (V9)
    Contract:      ../04-judge.md#routing

## Decision

When extraction resolves a subject that is a listed teammate, the fact is written to the **team** scope with that person as `subject_id` and the speaker as `author_id`. Not to the speaker's private scope, and not to the subject's private scope. It is visible to everyone on the team, and the person it is about can archive it, because their membership makes the team scope writable for them.

## Alternatives and why not

**Keep it in the speaker's private scope.** The conservative default, and it is the one that destroys the feature. "Саша в отпуске до марта" is worth remembering precisely because the next person to ask about Саша is not the person who said it. Filed privately, the team learns nothing and the same fact is re-learned by each member separately — which is the behaviour of five single-user instances, not a team memory.

**Write it into the subject's private scope.** Superficially the most respectful placement and the least defensible one. It would mean anybody can write into anybody's private space, which is the one guarantee a private scope makes. It also puts a fact about Саша, written by Bob, somewhere Bob can no longer see or correct — so a mistake is unfixable by the person who made it. And it inverts the meaning of "private": a scope that others can write to is a shared scope with a misleading name.

**A per-pair or per-subject scope.** One entity per "facts Bob knows about Саша" is precise and multiplies scopes by the square of the team. It also answers the wrong question: the team wants one picture of a person, not a per-observer set of them.

**Ask before sharing.** A confirmation step at write time reads as careful and would arrive in the wrong place — mid-conversation, from a hook, about a sentence the speaker has moved on from. The review queue is the same control moved to where a person is already reviewing: the fact is `pending`, it shows its author and its subject, and confirming or declining it is one click. The subject sees it in the same queue, because it is in their team scope.

## Consequences

Attribution is preserved in both directions: `author_id` says who wrote it, `subject_id` says who it is about, and the review queue and entity profile pages show both. A fact about a person is deliberately excluded from the team block of everyone else's session profile — it belongs on that person's page, not in the preamble of every session — while still being retrievable by a search that asks about them.

Consequence worth stating plainly: this makes the team scope the default destination for observations about people, so an instance where colleagues do not want to be observed should not run the extractor over their conversations. The control is the review queue and archival, not a routing rule that pretends the fact was never stated.

The rule fires only for a person in the entity block. An unresolved name keeps the fact private and unattributed and raises a review item ([0070](0070-numbered-entities-and-integer-routing.md)); guessing which teammate was meant would put a claim on the wrong person's profile, which is the failure this whole path exists to avoid.
