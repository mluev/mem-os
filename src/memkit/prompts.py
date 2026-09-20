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

REGISTRY: dict[str, str] = {"v7": V7, "v8": V8, "v9": V9, "v10": V10}
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
DEFAULT_VERSION = "v10"

CONSOLIDATE_V2 = """Compare the memories below. Return a merged text only when they
state the same claim in the same context. Preserve the newest truth and all useful
specifics. Return null when they differ. Never introduce workflow or scheduling
semantics. Keep the result under 200 characters.

MEMORIES
{cluster}"""
CONSOLIDATE_VERSION = "c2"


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
