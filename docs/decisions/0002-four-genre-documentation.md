# 0002 — Documentation splits into contract, measurement, decision, investigation

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: —
    Evidence:      —
    Code:          tools/docblocks.py, tests/test_docs_contract.py
    Contract:      ../README.md

## Decision

Every fact has exactly one home, chosen by asking what would change it:

| genre | home | test |
|---|---|---|
| contract — what the system must do | `01`–`08` | would this change if I changed the code? |
| measurement — anything produced by running something | `measurements.md` | would this change if I re-ran the eval? |
| decision — a choice with a live alternative | `decisions/` | would this change if I changed my mind? |
| investigation — how we found out, including what fooled us | `experiments/` | is this a story about the past? |

Three enforcement rules, which matter more than the taxonomy:

**Inline amendment annotations are banned in the numbered documents.** No
"correction:", no "measured:", no "actually implemented as". That pattern is what
produced three generations of contradictions — an annotation leaves the wrong
statement standing next to the right one, and a reader cannot tell which is
current. Edit the document; add a decision here if a choice was involved.
`tests/test_docs_contract.py` fails on the specific words that were used.

**Code comments cite decision ids, not document paths.** Roughly forty comments
pointed at documents by path, one of them at a line number in a file that has
since moved two hundred lines. Accepted decisions never move.

**No prompt text in prose.** The extractor prompt is in `prompts.REGISTRY`. A
copy in a document rots invisibly — see [0016](0016-one-home-for-prompt-text.md).

## Alternatives and why not

**Keep annotating in place.** It is what happened, and it produced a set of
documents that stated three different judge models and four different corpus
sizes, all as fact.

**One decisions file rather than a directory.** Code comments need citable ids
that never move; a section anchor in a growing file is not stable, and a
fifty-entry monolith becomes a fourth place for a fact to drift to.

**Generate the documents entirely from code.** `05-retrieval.md` is about 200
lines of which perhaps 20 are machine facts. Generating it would keep the
constants correct and delete the argued reasoning, which is most of the value.
The compromise is generated regions inside hand-written prose.
