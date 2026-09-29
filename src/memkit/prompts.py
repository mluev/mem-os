"""Versioned, domain-neutral prompt registry."""

from __future__ import annotations

import json
from typing import Any

V7 = """You extract durable, atomic memories from a conversation. Precision and
source fidelity matter more than recall: when uncertain, return no operation.

Return ADD, UPDATE, or DELETE operations only. Do not create workflow objects,
tasks, reminders, schedules, due dates, or product state. A memory is a claim that
can help a future agent and remains independently understandable.

RULES
1. Only a user's own words can support a memory. Assistant messages are context
   for resolving references only. Never extract assistant work logs, counts,
   summaries, plans, claims, or suggestions—even when the user says "go on",
   "okay", or otherwise acknowledges them.
2. Every ADD or UPDATE must cite one or more exact spans from USER messages only.
   For each citation, copy the smallest sufficient user substring word-for-word
   into `quote`. Also provide `start_char`/`end_char` if you can count them, but
   the system derives authoritative offsets from a unique exact quote. Never
   paraphrase a quote, cite an assistant message, or guess source text.
3. Emit nothing for temporary moods or states (today, tired, later, currently),
   one-off questions or definitions, acknowledgements, ordinary task requests,
   implementation steps, completed work, tickets, schedules, or facts stated only
   by the assistant. Repetition in an assistant message does not make it evidence.
4. Use `kind="preference"` for a user's taste, correction, constraint, or durable
   working style; `kind="fact"` for identity/contact/profile attributes; otherwise
   use one concise domain-neutral noun. Do not invent taxonomy variants such as
   `ux_preference`, `identity`, or `profile_info`.
5. Context defaults to empty. Personal preferences, identity, contact details,
   general working style, and rules stated as "always", "everywhere", "in all our
   products", or "in future" remain global even inside a workspace conversation.
   Copy caller context only for a claim about this named codebase/system or a
   decision that would be false elsewhere.
6. Importance guidance: identity/contact, hard constraints, and explicit durable
   "always/never" rules are 0.7–0.9; ordinary durable preferences and project
   architecture are 0.5–0.7; never raise transient content into memory.
7. Keep text under 200 characters, self-contained, and free of credential values.
   A request to remember a secret is not permission to store the value.
8. UPDATE or DELETE only a supplied candidate in the same context. Use UPDATE
   when user evidence corrects or replaces that candidate; do not duplicate it.
9. `valid_until` means the claim stops being true, never a deadline.

FINAL CHECK FOR EACH OPERATION
- durable and useful in a future conversation;
- supported only by exact cited user text;
- kind, context, importance, and candidate target follow the rules above;
- no credential, assistant-only detail, transient state, or one-off question.
If any check fails, omit the operation.

CONTEXT
{context}

CANDIDATES
{candidates}

CONVERSATION WINDOW
{window}"""

# v8 = v7 plus four measured-failure-mode guards and a temporal anchor. The date
# block exists because v7 gave the model no date at all: "last month" in a
# backfilled window resolved against nothing, and `valid_until` had no anchor.
# The failure modes are named after real misfires (mem0's public prompt work
# names the same four), each with one WRONG/RIGHT pair -- kept terse because
# input tokens are billed per call and the pairs teach more than paragraphs.
V8 = """You extract durable, atomic memories from a conversation. Precision and
source fidelity matter more than recall: when uncertain, return no operation.

Return ADD, UPDATE, or DELETE operations only. Do not create workflow objects,
tasks, reminders, schedules, due dates, or product state. A memory is a claim that
can help a future agent and remains independently understandable.

DATES
Today is {today}. The window below was recorded on {session_date}; the recording
date is the ONLY anchor for relative time. Convert relative references to absolute
dates against it: "last month" in a window recorded 2026-03-10 means 2026-02 even
when today is much later. Write only the absolute form — the relative phrase must
not survive into the memory text. Never rewrite an absolute date or duration into
a vaguer one ("18 days" stays "18 days", not "recently"). `valid_until` uses the
same anchor.

RULES
1. Only a user's own words can support a memory. Assistant messages are context
   for resolving references only. Never extract assistant work logs, counts,
   summaries, plans, claims, or suggestions—even when the user says "go on",
   "okay", or otherwise acknowledges them.
2. Every ADD or UPDATE must cite one or more exact spans from USER messages only.
   For each citation, copy the smallest sufficient user substring word-for-word
   into `quote`. Also provide `start_char`/`end_char` if you can count them, but
   the system derives authoritative offsets from a unique exact quote. Never
   paraphrase a quote, cite an assistant message, or guess source text.
3. Emit nothing for temporary moods or states (today, tired, later, currently),
   one-off questions or definitions, acknowledgements, ordinary task requests,
   implementation steps, completed work, tickets, schedules, or facts stated only
   by the assistant. Repetition in an assistant message does not make it evidence.
4. Use `kind="preference"` for a user's taste, correction, constraint, or durable
   working style; `kind="fact"` for identity/contact/profile attributes; otherwise
   use one concise domain-neutral noun. Do not invent taxonomy variants such as
   `ux_preference`, `identity`, or `profile_info`.
5. Context defaults to empty. Personal preferences, identity, contact details,
   general working style, and rules stated as "always", "everywhere", "in all our
   products", or "in future" remain global even inside a workspace conversation.
   Copy caller context only for a claim about this named codebase/system or a
   decision that would be false elsewhere. When you do, copy the key and the
   value from CONTEXT **character for character** — never rename, shorten, or
   invent a key, and never emit a key CONTEXT does not contain.
6. Importance guidance: identity/contact, hard constraints, and explicit durable
   "always/never" rules are 0.7–0.9; ordinary durable preferences and project
   architecture are 0.5–0.7; never raise transient content into memory.
7. Keep text under 200 characters, self-contained, and free of credential values.
   A request to remember a secret is not permission to store the value.
8. UPDATE or DELETE only a supplied candidate in the same context. Use UPDATE
   when user evidence corrects or replaces that candidate; do not duplicate it.
9. `valid_until` means the claim stops being true, never a deadline.
10. Keep proper nouns verbatim — product, repo, library, person, and place names.
    A memory is found by the names it contains: "a new restaurant" is unfindable,
    "Osteria Francescana" is not.
11. When the user states a change ("switched from X to Y", "renamed", "no
    longer"), capture the transition. If a candidate holds the old truth, UPDATE
    it; the new text states the current truth and what it replaced.

FAILURE MODES — check every operation against all four:
- Echo extraction. The assistant restating the user adds no second fact.
  WRONG: a memory cited from the assistant's "I've set daily check-ins at 7:30".
  RIGHT: one memory cited from the user's own "I want daily check-ins at 7:30".
- Meta-extraction. Record content, never the act of sharing it.
  WRONG: "User asked about JWT auth". RIGHT: nothing — a one-off question is not
  durable.
- Detail contamination. Never merge candidate or neighbouring-message details
  into a claim. WRONG: "User had a great meal at Olive Garden" when the cited
  message says only "I had a great meal" and Olive Garden appears elsewhere.
- First-topic dominance. Middle and late messages count equally; re-scan the
  whole window before returning.

FINAL CHECK FOR EACH OPERATION
- durable and useful in a future conversation;
- supported only by exact cited user text;
- kind, context, importance, and candidate target follow the rules above;
- relative dates resolved against the session date, absolutes kept absolute;
- no credential, assistant-only detail, transient state, or one-off question.
If any check fails, omit the operation.

CONTEXT
{context}

CANDIDATES
{candidates}

CONVERSATION WINDOW
{window}"""


# v9 = v8 plus routing. A team instance has more than one place a fact can go,
# and the model is the only participant that has just read the sentence, so it
# decides -- but only by number, and only among entities it was shown. Names
# and ids are never accepted: a uuid comes back mutated and a name comes back
# guessed, while an integer outside the block is provably fabricated.
V9 = V8.replace(
    """CONTEXT
{context}""",
    """ENTITIES (refer to them by number only; never invent a number)
{entities}

ROUTING
- A fact about the speaker — who they are, what they like, how they want you to
  work — needs no scope and no subject. This is the default; when torn between
  the speaker and the team, choose the speaker.
- A fact about a listed teammate ("Alex prefers dark mode", "Саша в отпуске до
  марта"): set subject to their number and omit scope. It becomes team-visible
  and that person can see it.
- A fact about a listed project, product or company: set scope to its number.
- A rule stated for everyone ("we always squash-merge", "у нас принято…"): set
  scope to the team's number, no subject.
- A person who is NOT in the list: omit scope and subject, and copy their name
  verbatim into `subject_name`. Do not guess which listed person was meant.

CONTEXT
{context}""",
)

# v10 = v9's routing capability, minus the context regression it came with.
#
# The measured diagnosis (docs/measurements.md#extractor-prompt-v8-against-v9):
# v9 put ENTITIES and ROUTING *ahead* of CONTEXT, so the model read "decide
# where this belongs" before it read "context defaults to empty", and it scoped
# more of what should have stayed global -- 8/14 down to 6/14. Three changes
# follow from that and nothing else does:
#
# 1. Routing comes after CONTEXT, so rule 5 is read first.
# 2. The two fields are named as different things. `scope_id` is *where the
#    memory lives*; `context` is a qualifier on *when the claim is true*. v9
#    never said so, and a model given one new placement field will happily use
#    the old one to mean the same thing.
# 3. Rule 5 gets an operational test instead of a list to pattern-match: would
#    this sentence still be true said in another repo tomorrow? That is the
#    question the failures were getting wrong, asked directly.
#
# Two clauses were added afterwards because the golden runs demanded them, and
# both are load-bearing rather than decorative:
#
# * "the test decides the context field and nothing else". Asked where a fact
#   belongs, the model started writing *more general* claims to make the answer
#   come out global, and a general claim drops specifics: recall fell to 27/31
#   and "OTP на почту, пароля нет" came back as "use dev@notiky.local for
#   login". Generalisation pressure and recall are the same dial.
# * "the workspace CONTEXT names is not a scope". Without it, a preference
#   stated while working in one repo was scoped to that repo -- the v9
#   regression, relocated from `context` to `scope_id`.
_V10_RULE_5 = """5. Context defaults to empty and stays empty unless the claim would be FALSE
   outside what CONTEXT names. Test it: said again tomorrow in another repo,
   would this sentence still hold? If yes, context is empty — personal
   preferences, identity, contact details, general working style, and rules
   stated as "always", "everywhere", "in all our products", or "in future" are
   global however project-heavy the surrounding session is. The test decides the
   context field and nothing else: never generalise the claim or drop a specific
   the user gave in order to make the answer come out "yes". Copy caller context
   only for a claim about this named codebase/system. When you do, copy the key
   and the value from CONTEXT **character for character** — never rename,
   shorten, or invent a key, and never emit a key CONTEXT does not contain."""

V10 = (
    V8.replace(
        """5. Context defaults to empty. Personal preferences, identity, contact details,
   general working style, and rules stated as "always", "everywhere", "in all our
   products", or "in future" remain global even inside a workspace conversation.
   Copy caller context only for a claim about this named codebase/system or a
   decision that would be false elsewhere. When you do, copy the key and the
   value from CONTEXT **character for character** — never rename, shorten, or
   invent a key, and never emit a key CONTEXT does not contain.""",
        _V10_RULE_5,
    )
    .replace(
        "- kind, context, importance, and candidate target follow the rules above;",
        "- kind, context, importance, and candidate target follow the rules above;\n"
        "- scope and subject are numbers printed in ENTITIES, or absent — and were\n"
        "  decided separately from context;",
    )
    .replace(
        """CANDIDATES
{candidates}""",
        """ENTITIES (refer to them by number only; never invent a number)
{entities}

ROUTING — which of those numbers owns the memory. Most operations need none.
Scope is not context: scope is where the memory lives, context is a qualifier on
when the claim is true. They are decided separately, and a scoped memory usually
still has empty context. The workspace CONTEXT names is not a scope; only a
number in ENTITIES is, and only the sentence can justify one.
- Default: no scope and no subject. Everything about the speaker — who they are,
  what they like, how they want you to work, including their own "always/never"
  rules — routes nowhere. When torn, choose the speaker. The project you happen
  to be working in is never a reason to scope their preference.
  WRONG: scope = the repo whose files you were editing when they said it.
  RIGHT: no scope; a working style is the speaker's, not the project's.
- A fact about a listed teammate ("Alex prefers dark mode", "Саша в отпуске до
  марта"): set subject to their number and omit scope.
- A fact about a listed project, product or company — its architecture, its
  conventions, its state: set scope to its number.
- A rule the user states for everyone ("we always squash-merge", "у нас
  принято…"): set scope to the team's number, no subject.
- A person who is NOT in the list: omit scope and subject, and copy their name
  into `subject_name` in the user's own spelling and script — never translated
  or transliterated. Do not guess which listed person was meant.
- Anything else with no number — an unlisted repo, product or company — is not
  routable. Never route to a number whose name is not the thing the sentence is
  about; empty is the right answer there, not a fallback.

CANDIDATES
{candidates}""",
    )
)

# v11 = v10 plus time, episodes and the memory graph (decisions/0075-0076).
#
# Rule 3 of every earlier version dropped anything temporary, completed or
# dated. That kept work logs out, and it also made every "when did I…" and
# "how many times…" question unanswerable: the evidence was discarded at the
# write. v11 keeps the work-log exclusion word for word and moves what a person
# *did or will do* into `kind="episode"` with absolute `event_dates`, and a
# state with a natural end into a memory whose `valid_until` is that end.
# Episodes decay at read time rather than being refused at write time.
#
# Three graph fields replace rule 11's single UPDATE. An UPDATE now says whether
# the candidate was wrong (`correction`, rewritten in place, as before) or was
# true until something changed (`supersede`, a new memory; the old one stays as
# dated history). An ADD may name the candidate it `extends`. Candidates show
# when they were said, so the model can tell a newer claim from an older one.
V11 = """You extract atomic, self-contained memories from a conversation between a
user and an assistant. Precision and source fidelity matter more than recall: when
uncertain, return no operation.

Return ADD, UPDATE, or DELETE operations only. Never create tasks, reminders or
to-dos for the assistant. A memory is one claim that helps a future conversation
and is understandable with no transcript: name who it is about (the user or the
person's name, never "I", "he" or "they") and resolve every "it", "there" and
"that project" into the names the window gives. A message stating several
independent facts yields several operations, one claim each.

DATES
Today is {today}. The window below was recorded on {session_date}; the recording
date is the ONLY anchor for relative time. Convert relative references to absolute
dates against it: "last month" in a window recorded 2026-03-10 means 2026-02 even
when today is much later. Write only the absolute form — the relative phrase must
not survive into the memory text. Never rewrite an absolute date or duration into
a vaguer one ("18 days" stays "18 days", not "recently"). `valid_until` and
`event_dates` use the same anchor.

`event_dates` is WHEN THE DESCRIBED THING HAPPENED OR WILL HAPPEN, not when it was
said: absolute dates at the precision the user gave — "2026", "2026-03", or
"2026-03-14". "Last Saturday" in a window recorded Wednesday 2026-03-18 is
"2026-03-14"; "in March" is "2026-03"; never invent a day the user did not give.
Leave it empty for timeless facts and preferences.

RULES
1. Only a user's own words can support a memory. Assistant messages are context
   for resolving references only. Never extract assistant work logs, counts,
   summaries, plans, claims, or suggestions—even when the user says "go on",
   "okay", or otherwise acknowledges them.
2. Every ADD or UPDATE must cite one or more exact spans from USER messages only.
   For each citation, copy the smallest sufficient user substring word-for-word
   into `quote`. Also provide `start_char`/`end_char` if you can count them, but
   the system derives authoritative offsets from a unique exact quote. Never
   paraphrase a quote, cite an assistant message, or guess source text.
3. Emit nothing for one-off questions or definitions, acknowledgements, greetings,
   ordinary task requests to the assistant, implementation steps, tickets, or the
   assistant's work in this session ("run the tests", "fix that bug", "done"), or
   facts stated only by the assistant. Repetition in an assistant message does
   not make it evidence. A passing mood with no consequence ("I'm tired") is
   nothing.
4. Kinds: `kind="preference"` for a user's taste, correction, constraint, or
   durable working style; `kind="fact"` for identity, contact, relationships,
   possessions, and other stable attributes; `kind="episode"` for something the
   user or a named person did, experienced, attended, bought, started, finished,
   or will do at a particular time — "The user ran the Lisbon half marathon on
   2026-03-14". An episode always has `event_dates` and states its date in the
   text. Otherwise use one concise domain-neutral noun. Do not invent taxonomy
   variants such as `ux_preference`, `identity`, `event`, or `profile_info`.
5. Context defaults to empty and stays empty unless the claim would be FALSE
   outside what CONTEXT names. Test it: said again tomorrow in another repo,
   would this sentence still hold? If yes, context is empty — personal
   preferences, identity, contact details, general working style, and rules
   stated as "always", "everywhere", "in all our products", or "in future" are
   global however project-heavy the surrounding session is. The test decides the
   context field and nothing else: never generalise the claim or drop a specific
   the user gave in order to make the answer come out "yes". Copy caller context
   only for a claim about this named codebase/system. When you do, copy the key
   and the value from CONTEXT **character for character** — never rename,
   shorten, or invent a key, and never emit a key CONTEXT does not contain.
6. Importance: identity/contact, hard constraints, explicit durable
   "always/never" rules, and life events (moving, a new job, a birth, a
   diagnosis) are 0.7–0.9; ordinary durable preferences and project architecture
   are 0.5–0.7; ordinary episodes are 0.3–0.6.
7. Keep text under 200 characters and free of credential values. A request to
   remember a secret is not permission to store the value.
8. A state with a natural end ("on vacation until March 10", "my exam is
   tomorrow", "staying in Berlin this week") is a memory whose `valid_until` is
   that end. `valid_until` means the claim stops being true, never a deadline.
9. `is_static` is true only for enduring identity traits that should color every
   conversation — name, pronouns, native language, hometown, profession,
   family members. Preferences, episodes and project facts are not static.
10. Keep proper nouns verbatim — product, repo, library, person, and place names.
    A memory is found by the names it contains: "a new restaurant" is unfindable,
    "Osteria Francescana" is not. Keep numbers, quantities and prices exactly.
11. CANDIDATES are existing memories; each shows when it was said. Never ADD a
    claim a candidate already states. UPDATE or DELETE only a supplied candidate
    in the same context, and give every UPDATE a `change`:
    - "correction": the candidate was wrong or imprecise; its text is rewritten.
    - "supersede": the candidate WAS true and the situation has since changed
      ("switched from npm to pnpm", "moved to Lisbon", "no longer at Acme"). The
      new text states the current truth; the old memory is kept as history.
    An ADD that adds detail to one candidate without contradicting it sets
    `extends` to that candidate's number ("Alex leads a team of five" extends
    "Alex is a PM at Stripe").

FAILURE MODES — check every operation against all five:
- Echo extraction. The assistant restating the user adds no second fact.
  WRONG: a memory cited from the assistant's "I've set daily check-ins at 7:30".
  RIGHT: one memory cited from the user's own "I want daily check-ins at 7:30".
- Meta-extraction. Record content, never the act of sharing it.
  WRONG: "User asked about JWT auth". RIGHT: nothing — a one-off question is not
  durable.
- Detail contamination. Never merge candidate or neighbouring-message details
  into a claim. WRONG: "User had a great meal at Olive Garden" when the cited
  message says only "I had a great meal" and Olive Garden appears elsewhere.
- First-topic dominance. Middle and late messages count equally; re-scan the
  whole window before returning.
- Lost dates. An episode without `event_dates`, or "recently" where the user gave
  a date. WRONG: "The user adopted a dog". RIGHT: "The user adopted a beagle
  named Max on 2026-02-01" with event_dates ["2026-02-01"].

FINAL CHECK FOR EACH OPERATION
- useful in a future conversation, and one claim;
- supported only by exact cited user text;
- kind, context, importance, and candidate target follow the rules above;
- scope and subject are numbers printed in ENTITIES, or absent — and were
  decided separately from context;
- relative dates resolved against the session date, absolutes kept absolute,
  and every episode dated;
- no credential, assistant-only detail, assistant work log, or one-off question.
If any check fails, omit the operation.

CONTEXT
{context}

ENTITIES (refer to them by number only; never invent a number)
{entities}

ROUTING — which of those numbers owns the memory. Most operations need none.
Scope is not context: scope is where the memory lives, context is a qualifier on
when the claim is true. They are decided separately, and a scoped memory usually
still has empty context. The workspace CONTEXT names is not a scope; only a
number in ENTITIES is, and only the sentence can justify one.
- Default: no scope and no subject. Everything about the speaker — who they are,
  what they like, how they want you to work, what they did, including their own
  "always/never" rules — routes nowhere. When torn, choose the speaker. The
  project you happen to be working in is never a reason to scope their
  preference.
  WRONG: scope = the repo whose files you were editing when they said it.
  RIGHT: no scope; a working style is the speaker's, not the project's.
- A fact about a listed teammate ("Alex prefers dark mode", "Саша в отпуске до
  марта"): set subject to their number and omit scope.
- A fact about a listed project, product or company — its architecture, its
  conventions, its state: set scope to its number.
- A rule the user states for everyone ("we always squash-merge", "у нас
  принято…"): set scope to the team's number, no subject.
- A person who is NOT in the list: omit scope and subject, and copy their name
  into `subject_name` in the user's own spelling and script — never translated
  or transliterated. Do not guess which listed person was meant. The speaker's
  own family and friends are not teammates: "The user's sister Emma graduated"
  is the speaker's memory and needs no `subject_name`.
- Anything else with no number — an unlisted repo, product or company — is not
  routable. Never route to a number whose name is not the thing the sentence is
  about; empty is the right answer there, not a fallback.

CANDIDATES
{candidates}

CONVERSATION WINDOW
{window}"""

REGISTRY: dict[str, str] = {"v7": V7, "v8": V8, "v9": V9, "v10": V10, "v11": V11}
# v10 is the default, and v9 never was. v9 bought routing at the cost of context
# accuracy (8/14 -> 6/14) with its own routing unmeasured, so it stayed on the
# shelf. v10 was measured against v8 on the same run, with the golden harness
# now scoring scope and subject: equal recall (28/31), zero leaks, zero false
# positives, zero invalid evidence, routing 7/7 against v8's 3/7, and context
# 15/18 against 9/17 -- the context metric improved rather than regressed,
# because rule 5 is read before the routing block instead of after it. It reads
# 42% more input tokens than v8 -- 13% more total cost, since output dominates
# the bill -- which is what the routing rules and the entity block weigh.
# See docs/measurements.md#extractor-prompt-v8-against-v10.
#
# v11 is the default because the store now has somewhere to put what v10 threw
# away -- event dates, episodes, supersession -- and a v10 extraction would leave
# those columns empty forever. It is unmeasured on the golden set at the time of
# writing; `memkit eval` and the LoCoMo/LongMemEval harness (eval/bench) are the
# measurements that decide whether it stays. Rolling back is naming "v10" in
# MEMKIT_PROMPT_VERSION; the new op fields are optional, so v10 output still
# parses and applies.
DEFAULT_VERSION = "v11"

CONSOLIDATE_V2 = """Compare the memories below. Return a merged text only when they
state the same claim in the same context. Preserve the newest truth and all useful
specifics. Return null when they differ. Never introduce workflow or scheduling
semantics. Keep the result under 200 characters.

MEMORIES
{cluster}"""
CONSOLIDATE_VERSION = "c2"


# Dreaming (decisions/0078): a second pass over memories that were written one
# window at a time, looking at a small cluster of related ones together. It
# finds what no single window could: that a later claim replaced an earlier
# one said in another session, that one adds detail to another, and what the
# cluster implies that none of them states. Inferences are written with their
# own provenance, start pending, and rank below stated facts until confirmed.
DREAM_V1 = """You maintain one person's or one team's memory. The numbered
memories below all live in the same space; each shows when it was said. Report
only what is clearly there. Returning nothing is correct far more often than
returning something.

LINKS between two memories, by number:
- "updates": memory FROM replaced memory TO. TO was true; FROM, said on or after
  TO's date, says the same attribute of the same person or thing has since
  changed ("moved to Lisbon" updates "lives in Porto"; "switched to pnpm" updates
  "uses npm"). Never for two claims that can both be true.
- "extends": FROM adds detail to TO without contradicting it ("leads a team of
  five" extends "is a PM at Stripe").
Never link memories that merely share a topic, a person, or a date.

INFERENCES: at most two new claims that follow with high confidence from two or
more of the memories taken together, and that none of them states alone —
"Alex works on Stripe's payments product" from "Alex is a PM at Stripe" and
"Alex spends every day on payment APIs". Each inference:
- names who or what it is about, like the memories do, in under 200 characters;
- lists every memory it depends on in `premises`;
- uses only names, numbers and dates the premises contain;
- is useful in a future conversation, not a summary or a restatement;
- never speculates about health, feelings, beliefs, finances, relationships or
  anything else a person would not want guessed about them.

MEMORIES
{memories}"""
DREAM_VERSION = "d1"


def render_dream(memories: list[dict[str, Any]]) -> str:
    lines = []
    for number, memory in enumerate(memories, start=1):
        events = memory.get("event_dates") or []
        when = f"said {memory.get('said') or 'unknown'}"
        if events:
            when += f"; happened {', '.join(events)}"
        lines.append(f"{number}. ({memory.get('kind')}; {when}) {memory['text']}")
    return DREAM_V1.format(memories="\n".join(lines))


def dream_schema() -> dict[str, Any]:
    """Links and inferences, every property required for strict mode."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "from": {"type": "integer"},
                        "to": {"type": "integer"},
                        "relation": {"type": "string", "enum": ["updates", "extends"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["from", "to", "relation", "reason"],
                },
            },
            "inferences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "text": {"type": "string"},
                        "kind": {"type": "string"},
                        "premises": {"type": "array", "items": {"type": "integer"}},
                        "confidence": {"type": "number"},
                    },
                    "required": ["text", "kind", "premises", "confidence"],
                },
            },
        },
        "required": ["links", "inferences"],
    }


# Query rewriting (decisions/0079). A question and the memory that answers it
# are worded differently -- "where do I live now?" against "The user moved to
# Lisbon" -- and a short query gives the lexical arm almost nothing. Rewrites
# are searched alongside the original and fused by rank, so a bad rewrite can
# add noise at the tail but cannot remove what the original query found.
REWRITE_V1 = """Rewrite a search query for a store of short, self-contained
memories about a person or a team ("The user moved to Lisbon on 2026-04-02",
"The team always squash-merges").

Return up to three alternative queries that ask for the same information in
other words:
- turn the question into the statement that would answer it ("where do I live"
  -> "the user lives in", "moved to");
- name the attribute or event it asks about, and expand abbreviations;
- keep every name, number and date from the query exactly;
- never add a fact, a name or a date the query does not contain;
- write in the language of the query.

QUERY
{query}"""
REWRITE_VERSION = "q1"


def render_rewrite(query: str) -> str:
    return REWRITE_V1.format(query=query)


def rewrite_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
        "required": ["queries"],
    }


# Forget-matching (decisions/0080). Search finds what shares words or meaning
# with a request; the model decides which of those are actually about what the
# person asked to forget, by number, among the candidates it was shown.
FORGET_V1 = """A person asked to forget: {request}

Below are memories that might match. Return the numbers of the memories that are
about what they asked to forget — the same topic, person, project or thing — and
leave out anything that only shares a word or a date with it. When unsure, leave
it out: forgetting the wrong memory is worse than keeping one.

MEMORIES
{memories}"""
FORGET_VERSION = "f1"


def render_forget(request: str, memories: list[str]) -> str:
    listed = "\n".join(f"{number}. {text}" for number, text in enumerate(memories, start=1))
    return FORGET_V1.format(request=request, memories=listed)


def forget_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"forget": {"type": "array", "items": {"type": "integer"}}},
        "required": ["forget"],
    }


def render(
    version: str,
    *,
    today: str,
    window: str,
    candidates: str,
    context: str | None = None,
    entities: str | None = None,
    session_date: str | None = None,
    profile: str = "",
    agent_id: str | None = None,
) -> str:
    del profile, agent_id
    template = REGISTRY.get(version)
    if template is None:
        raise ValueError(f"unknown prompt version: {version!r}")
    # Each version takes only the placeholders it declares; str.format ignores
    # the rest. A window with no recorded date anchors to today, which is exact
    # for live traffic and the least-wrong answer for undated backfills.
    # str.format ignores placeholders a version does not declare, so an older
    # prompt keeps rendering unchanged as newer inputs are added.
    return template.format(
        context=context or "{}",
        candidates=candidates,
        entities=entities or "(none)",
        window=window,
        today=today,
        session_date=session_date or today,
    )


def render_consolidate(facts: list[dict[str, Any]]) -> str:
    cluster = "\n".join(
        f"- id={fact['id']} kind={fact.get('kind')} "
        f"context={json.dumps(fact.get('context') or {}, ensure_ascii=False)}: "
        f"{fact['text']}"
        for fact in facts
    )
    return CONSOLIDATE_V2.format(cluster=cluster)


def render_profile(facts: list[dict[str, Any]], limit: int = 12) -> str:
    return "\n".join(
        f"- ({fact.get('kind')}, importance {fact.get('importance')}) {fact.get('text')}"
        for fact in facts[:limit]
    )
