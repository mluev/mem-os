"""Versioned extractor prompts.

Every memory records the `extraction_version` that produced it, so several
versions can coexist in one store and be compared on the same eval rather than
swapped on faith. That is the whole point of docs/04-judge.md's versioning rule.

Measured history, on 20-25 windows of the same corpus each:

v1  Claude Sonnet 5. Median fact 354 chars, longest 2161 -- an entire session
    changelog stored as one "memory". 16 of 16 facts were scope=project; not one
    described the user. 0.92 operations per call.
v2  Adds a hard length cap, worked examples of changelog-vs-fact, an explicit
    all-three-scopes rule, and truncated assistant turns in the window. Median
    fact fell to 103 chars, longest 185, and 5 of 6 facts became scope=user.
    But recall collapsed: 0.30 operations per call, 15 of 20 windows empty, and
    importance still only ever 0.6 or 0.7.
v3  Targets exactly those two v2 regressions. See the notes on WHAT CHANGED
    below.
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------
# Shared blocks
# --------------------------------------------------------------------------

_WORKED_EXAMPLES = """  BAD  "Merged PR #203, fixed 3 stale test suites, 162/162 suites green"
  GOOD "Auth for the API lives in auth/ and uses session cookies, not JWT"

  BAD  "User implemented converting LMS subpages into modal/drawer patterns,
        built side-drawer editors at 880px, deleted old route-level files"
  GOOD "Prefers drawer/modal editors over separate route pages in the LMS UI\""""

_CREDENTIALS_RULE = """Never store credentials, tokens, keys, connection strings, file contents,
   or command output. If a message contains them, extract only the surrounding
   intent, never the value."""

_TASK_STATUS_RULE = """TASK WORKFLOW STATUS
Set task_status only for type=task and only when the conversation is explicit:
  todo     clearly planned, assigned, requested, or not yet started
  doing    explicitly in progress now
  done     explicitly completed, fixed, shipped, or resolved
  unknown  the task exists but its workflow state is unclear
For non-task memories task_status must be null. Do not guess progress from tone."""


V2 = """You extract long-term memories from a conversation.

THE TEST FOR EVERY MEMORY
Would this still be worth knowing in three months? If it is only true of this
one session's work, it is not a memory. A changelog is not a memory.

{examples}

RULES

1. ONE FACT PER OPERATION, AT MOST TWO SENTENCES, UNDER 200 CHARACTERS.
   If you are writing a list, a summary, or anything with semicolons joining
   unrelated points, you are writing a changelog. Split it or drop it.
2. Self-contained. Someone reading it in a year, with no other context, must
   understand it. Never write "he", "it", "this project".
3. Resolve relative time to absolute dates. Today is {today}.
   "last month" -> "(June 2026)".
4. Store what is true about the user and their world. Do NOT store what the
   assistant did. The assistant's turns are context only -- they are there so
   you can resolve "it" and "that project", never as source material. Prefixing
   "User implemented..." to a summary of the assistant's work does not make it
   a fact about the user.
5. All three scopes matter, and each earns its keep differently:
     scope=user     durable across every project -- preferences, identity,
                    skills, working style, tools they insist on
     scope=project  durable for the life of one codebase -- where things live,
                    architectural decisions and the reason behind them
     scope=task     only for genuinely short-lived work; these expire in days
   A window of technical work usually contains BOTH: what the user prefers in
   general, and what was decided about this codebase. Look for both. If you
   emit only project facts from a long conversation, you have probably missed
   the user's preferences hiding in how they asked for things.
6. If new information contradicts or refines a CANDIDATE, emit UPDATE with
   that candidate's id. Do not emit ADD.
7. Returning an empty operations list is correct and common. Most windows
   contain nothing worth remembering.
8. Write the memory in the same language the user used.
9. {credentials}

IMPORTANCE -- use the full range; do not cluster everything in the middle
  0.9-1.0  identity and hard constraints: who they are, what they will not do,
           things that should shape almost every answer
  0.7-0.8  strong stable preferences and real skills: tools they insist on,
           languages they work in daily, firm architectural positions
  0.4-0.6  useful but narrow: where one module lives, one decision's reason
  0.1-0.3  weak signal, mentioned once, probably situational
  below    do not emit at all
A single conversation should not produce five facts all at 0.5. Differentiate.

CANDIDATES (existing memories, may be empty)
{candidates}

CONVERSATION WINDOW
Assistant turns are truncated on purpose: they are context, not content.
{window}"""


# WHAT CHANGED IN v3, and why
#
# 1. A CONTEXT block. v2 told the model nothing about where it was. The project
#    name was computed and then never shown; the session date was absent; and
#    CANDIDATES are chosen by vector similarity to the window, so a window about
#    CSS surfaces eight CSS facts and nothing about who the person is. v3 adds
#    the project, the session date, and a separate PROFILE block of the highest-
#    importance user-scope facts -- selected by importance, not similarity, so it
#    is stable across windows.
#
# 2. Recall. v2 produced 0.30 operations per call against Sonnet's 0.92, with 15
#    of 20 windows empty. Rule 7 ("empty is correct and common") combined with a
#    hard length cap appears to have over-damped it. v3 keeps the permission to
#    return nothing but names the signals that *should* produce a fact, so
#    "nothing" has to be a decision rather than a default.
#
# 3. Importance. v2's numeric bands did not move the model off 0.6/0.7. v3
#    attaches a concrete worked example to each band, which is what the bands
#    were missing -- an anchor the model can pattern-match against.
V3 = """You extract long-term memories from a conversation.

THE TEST FOR EVERY MEMORY
Would this still be worth knowing in three months? If it is only true of this
one session's work, it is not a memory. A changelog is not a memory.

{examples}

CONTEXT
{context}

WHAT IS ALREADY KNOWN ABOUT THIS PERSON
Do not re-add any of this. Use it to judge what is genuinely new, and to write
facts that fit what you already know rather than contradicting it.
{profile}

RULES

1. ONE FACT PER OPERATION, AT MOST TWO SENTENCES, UNDER 200 CHARACTERS.
   If you are writing a list, a summary, or anything with semicolons joining
   unrelated points, you are writing a changelog. Split it or drop it.
2. Self-contained. Someone reading it in a year, with no other context, must
   understand it. Never write "he", "it", "this project" -- name the project
   from CONTEXT instead.
3. Resolve relative time to absolute dates. This conversation happened on
   {session_date}; today is {today}. "last month" -> "(June 2026)".
4. Store what is true about the user and their world. Do NOT store what the
   assistant did. The assistant's turns are context only -- they are there so
   you can resolve "it" and "that project", never as source material. Prefixing
   "User implemented..." to a summary of the assistant's work does not make it
   a fact about the user.
5. All three scopes matter, and each earns its keep differently:
     scope=user     durable across every project -- preferences, identity,
                    skills, working style, tools they insist on
     scope=project  durable for the life of one codebase -- where things live,
                    architectural decisions and the reason behind them
     scope=task     only for genuinely short-lived work; these expire in days
   A window of technical work usually contains BOTH: what the user prefers in
   general, and what was decided about this codebase. Look for both.
6. If new information contradicts or refines a CANDIDATE, emit UPDATE with
   that candidate's id. Do not emit ADD.

7. WHAT TO LOOK FOR. Returning an empty list is legitimate, but it should be a
   conclusion, not a reflex. Read the user's turns once more and ask whether any
   of these appeared -- each is worth a memory:
     - a preference, stated or implied by a correction
       ("no, use X instead", "don't do Y", "I'd rather...")
     - an opinion about how something should look, work, or be built
     - a decision, and ideally the reason for it
     - a fact about the person: identity, contacts, location, employer, tools
     - a constraint they work under, or something they refuse to do
     - a recurring irritation or something they call out as wrong
   A correction is the single richest signal there is: when the user rejects
   something the assistant proposed, the reason behind the rejection is almost
   always a durable preference. Extract the preference, not the rejection.
   Only if none of the above is present is the empty list the right answer.

8. Write the memory in the same language the user used.
9. {credentials}

IMPORTANCE -- differentiate; do not cluster everything at 0.6-0.7
  0.9-1.0  identity and hard constraints, shaping almost every answer
           e.g. "Lives in Tashkent, works in Russian and English"
                "Will not use a framework without TypeScript support"
  0.7-0.8  strong stable preferences and real skills
           e.g. "Prefers pnpm over npm in every project"
                "Writes Vue 3 with TypeScript daily; weak on Rust"
  0.4-0.6  useful but narrow: one module's location, one decision's reason
           e.g. "LMS course editor lives in a drawer, not a route page"
  0.1-0.3  weak signal, mentioned once, probably situational
           e.g. "Was annoyed by a flaky test on 2026-07-14"
  below    do not emit at all
If two facts in one window get the same importance, check that they really are
equally load-bearing.

CANDIDATES (similar existing memories, may be empty)
{candidates}

CONVERSATION WINDOW
Assistant turns are truncated on purpose: they are context, not content.
{window}"""


# WHAT CHANGED IN v4
#
# v3 tested two ideas at once and one of them was actively harmful, which the
# golden set located precisely: naming the project in a CONTEXT block primes the
# model to file *everything* under that project. On the golden set v3 filed a
# stated pnpm preference and the user's own GitHub handle as scope=project, and
# dropped the identity fact's importance to 0.5. On the real corpus the same
# effect produced 0% user-scope facts.
#
# v4 keeps what worked and drops what did not:
#   kept from v2   the scope rule verbatim (6/6 correct on the golden set) and
#                  the length cap (median fact 84 chars, nothing over 200)
#   kept from v3   the WHAT TO LOOK FOR block, which did not hurt recall, and
#                  the worked importance examples
#   changed        the project is still named -- rule 2 needs it, or facts say
#                  "this project" -- but with an explicit warning that naming it
#                  says nothing about scope
#   dropped        the profile block. On the real corpus it suppressed user-scope
#                  recall: told "do not re-add any of this", the model concluded
#                  there was nothing new about the person. Deduplication is the
#                  CANDIDATES block's job and it already does it.
V4 = """You extract long-term memories from a conversation.

THE TEST FOR EVERY MEMORY
Would this still be worth knowing in three months? If it is only true of this
one session's work, it is not a memory. A changelog is not a memory.

{examples}

WHERE THIS CONVERSATION HAPPENED
{context}
This tells you what to call things -- it does NOT tell you the scope. A person
states their preferences and facts about themselves while working inside a
repository; those are still scope=user. Deciding scope from the repository name
is the single most common mistake here.

RULES

1. ONE FACT PER OPERATION, AT MOST TWO SENTENCES, UNDER 200 CHARACTERS.
   If you are writing a list, a summary, or anything with semicolons joining
   unrelated points, you are writing a changelog. Split it or drop it.
2. Self-contained. Someone reading it in a year, with no other context, must
   understand it. Never write "he", "it", "this project" -- name the project.
3. Resolve relative time to absolute dates. This conversation happened on
   {session_date}; today is {today}. "last month" -> "(June 2026)".
4. Store what is true about the user and their world. Do NOT store what the
   assistant did. The assistant's turns are context only -- they are there so
   you can resolve "it" and "that project", never as source material. Prefixing
   "User implemented..." to a summary of the assistant's work does not make it
   a fact about the user.
5. All three scopes matter, and each earns its keep differently:
     scope=user     durable across every project -- preferences, identity,
                    skills, working style, tools they insist on
     scope=project  durable for the life of one codebase -- where things live,
                    architectural decisions and the reason behind them
     scope=task     only for genuinely short-lived work; these expire in days
   A window of technical work usually contains BOTH: what the user prefers in
   general, and what was decided about this codebase. Look for both. If you
   emit only project facts from a long conversation, you have probably missed
   the user's preferences hiding in how they asked for things.
6. If new information contradicts or refines a CANDIDATE, emit UPDATE with
   that candidate's id. Do not emit ADD.

7. WHAT TO LOOK FOR. Returning an empty list is legitimate, but it should be a
   conclusion, not a reflex. Read the user's turns once more and ask whether any
   of these appeared -- each is worth a memory:
     - a preference, stated or implied by a correction
       ("no, use X instead", "don't do Y", "I'd rather...")
     - an opinion about how something should look, work, or be built
     - a decision, and ideally the reason for it
     - a fact about the person: identity, contacts, location, employer, tools
     - a constraint they work under, or something they refuse to do
     - a recurring irritation or something they call out as wrong
   A correction is the single richest signal there is: when the user rejects
   something the assistant proposed, the reason behind the rejection is almost
   always a durable preference. Extract the preference, not the rejection.

8. WHAT IS NOT A MEMORY, no matter how clearly stated:
     - how the user feels right now: tired, busy, in a hurry, frustrated
     - what they are doing today, unless it outlives the week
     - a topic they asked about once ("what is tRPC?" is curiosity, not interest)
     - the assistant's own output: files touched, tests run, PRs merged
   If a window contains only these, the empty list is the right answer.

9. Write the memory in the same language the user used.
10. {credentials}

{task_status}

IMPORTANCE -- differentiate; do not cluster everything at 0.6-0.7
  0.9-1.0  identity and hard constraints, shaping almost every answer
           e.g. "Lives in Tashkent, works in Russian and English"
                "Will not run local LLMs; 16GB machine, API only"
  0.7-0.8  strong stable preferences and real skills
           e.g. "Prefers pnpm over npm in every project"
                "Writes Vue 3 with TypeScript daily; weak on Rust"
  0.4-0.6  useful but narrow: one module's location, one decision's reason
           e.g. "LMS course editor lives in a drawer, not a route page"
  0.1-0.3  weak signal, mentioned once, probably situational
  below    do not emit at all
Identity and contact details are never below 0.7. If two facts in one window get
the same importance, check that they really are equally load-bearing.

CANDIDATES (similar existing memories, may be empty)
{candidates}

CONVERSATION WINDOW
Assistant turns are truncated on purpose: they are context, not content.
{window}"""


# WHAT CHANGED IN v5
#
# v4 raised recall 49% on the real corpus (0.43 -> 0.64 facts per window) but
# user-scope facts fell from 33% to 11%. The golden set did not catch it: its
# cases are short and unambiguous, so the anti-priming warning was enough there
# (6/6 scope correct) while real project-heavy windows overwhelmed it.
#
# v5 isolates the variable: v4 exactly, minus any mention of the project. If
# recall holds and user-scope recovers, the project name was the cause and the
# warning was never going to be enough -- the fix has to be structural, not
# worded. Rule 2 loses its naming aid, so it asks for a description instead.
V5 = """You extract long-term memories from a conversation.

THE TEST FOR EVERY MEMORY
Would this still be worth knowing in three months? If it is only true of this
one session's work, it is not a memory. A changelog is not a memory.

{examples}

RULES

1. ONE FACT PER OPERATION, AT MOST TWO SENTENCES, UNDER 200 CHARACTERS.
   If you are writing a list, a summary, or anything with semicolons joining
   unrelated points, you are writing a changelog. Split it or drop it.
2. Self-contained. Someone reading it in a year, with no other context, must
   understand it. Never write "he", "it", "this project" -- describe the thing
   concretely instead ("the LMS course editor", "the attendance report modal").
3. Resolve relative time to absolute dates. This conversation happened on
   {session_date}; today is {today}. "last month" -> "(June 2026)".
4. Store what is true about the user and their world. Do NOT store what the
   assistant did. The assistant's turns are context only -- they are there so
   you can resolve "it" and "that project", never as source material. Prefixing
   "User implemented..." to a summary of the assistant's work does not make it
   a fact about the user.

5. SCOPE. Decide this from what the fact is *about*, never from what the
   conversation was about. Almost every window here is technical work inside a
   repository; that says nothing about scope.
     scope=user     true of the person wherever they work: preferences, taste,
                    identity, contacts, skills, working style, tools they insist
                    on, things they refuse to do. If the same sentence would
                    still be true in a different repository, it is scope=user.
     scope=project  true of one codebase and meaningless outside it: where a
                    module lives, an architectural decision and its reason,
                    a naming convention specific to that code.
     scope=task     genuinely short-lived work, expiring within days.
   Test each fact: "would this still hold if they switched to another project?"
   Yes -> user. No -> project. A sentence starting "Prefers..." or "Wants..."
   is almost always about the person, even when the example that revealed it
   came from one repository.

6. If new information contradicts or refines a CANDIDATE, emit UPDATE with
   that candidate's id. Do not emit ADD.

7. WHAT TO LOOK FOR. Returning an empty list is legitimate, but it should be a
   conclusion, not a reflex. Read the user's turns once more and ask whether any
   of these appeared -- each is worth a memory:
     - a preference, stated or implied by a correction
       ("no, use X instead", "don't do Y", "I'd rather...")
     - an opinion about how something should look, work, or be built
     - a decision, and ideally the reason for it
     - a fact about the person: identity, contacts, location, employer, tools
     - a constraint they work under, or something they refuse to do
     - a recurring irritation or something they call out as wrong
   A correction is the single richest signal there is: when the user rejects
   something the assistant proposed, the reason behind the rejection is almost
   always a durable preference. Extract the preference, not the rejection.

8. WHAT IS NOT A MEMORY, no matter how clearly stated:
     - how the user feels right now: tired, busy, in a hurry, frustrated
     - what they are doing today, unless it outlives the week
     - a topic they asked about once ("what is tRPC?" is curiosity, not interest)
     - the assistant's own output: files touched, tests run, PRs merged
   If a window contains only these, the empty list is the right answer.

9. Write the memory in the same language the user used.
10. {credentials}

{task_status}

IMPORTANCE -- differentiate; do not cluster everything at 0.6-0.7
  0.9-1.0  identity and hard constraints, shaping almost every answer
           e.g. "Lives in Tashkent, works in Russian and English"
                "Will not run local LLMs; 16GB machine, API only"
  0.7-0.8  strong stable preferences and real skills
           e.g. "Prefers pnpm over npm in every project"
                "Writes Vue 3 with TypeScript daily; weak on Rust"
  0.4-0.6  useful but narrow: one module's location, one decision's reason
  0.1-0.3  weak signal, mentioned once, probably situational
  below    do not emit at all
Identity and contact details are never below 0.7.

CANDIDATES (similar existing memories, may be empty)
{candidates}

CONVERSATION WINDOW
Assistant turns are truncated on purpose: they are context, not content.
{window}"""


# WHAT CHANGED IN v6
#
# Measured on the full corpus under v4: 41 of 62 facts came back scope=project and
# only 21 scope=user, so just 34% of the store was reachable without naming a
# project. Hand-reading the 41, roughly 17 were personal preferences bound to a
# repository by their own wording -- "For frontend-second, prefers modal dialogs
# with tabs", "For the notiky project, expects thorough code reviews". Those would
# still be true in another repository, which is v5 rule 5's own test for
# scope=user.
#
# v4 already warns that naming the project says nothing about scope. The warning
# reduces the drift and does not remove it. v5 tried the opposite -- delete the
# project entirely -- and lost recall without recovering user-scope, so the cause
# is not the project name being *present*.
#
# v6 changes who decides. The model still fills `scope`, but it must *separately*
# answer a yes/no question per fact: would this sentence still be true in another
# project? `judge.Op.parse` then promotes project -> user when the answer is yes.
# The mapping belongs to code, so the repository name has nowhere to leak into.
# The correction is one-directional by design: a user-scoped fact is never demoted
# to project, so v6 cannot regress the direction that was measured.
#
# The travel test is *appended* to v4's rule 5, not substituted for it. First
# attempt replaced the rule wholesale and recall collapsed 5x on real windows --
# 0.10 facts per window against v4's 0.50, 18 of 20 windows empty. The cause was
# not the new question but what the replacement deleted: v4's rule 5 actively
# pushes for more facts ("a window usually contains BOTH... Look for both"), and
# that clause is the recall driver. The test now labels a fact that already
# exists and says so explicitly, so it cannot act as a gate on emitting one.
#
# Also dropped: the old rule 9, "write the memory in the same language the user
# used". Measured, it was ignored ~70% of the time -- 20% of input is Russian
# against 6% of facts -- and it buys nothing: a Russian query retrieves the
# matching English fact at rank 1, which is what BGE-M3 was chosen for. One
# language also keeps dedup and consolidation cosines comparable.
V6 = """You extract long-term memories from a conversation.

THE TEST FOR EVERY MEMORY
Would this still be worth knowing in three months? If it is only true of this
one session's work, it is not a memory. A changelog is not a memory.

{examples}

WHERE THIS CONVERSATION HAPPENED
{context}
This tells you what to call things -- it does NOT tell you the scope. A person
states their preferences and facts about themselves while working inside a
repository; those are still scope=user. Deciding scope from the repository name
is the single most common mistake here.

RULES

1. ONE FACT PER OPERATION, AT MOST TWO SENTENCES, UNDER 200 CHARACTERS.
   If you are writing a list, a summary, or anything with semicolons joining
   unrelated points, you are writing a changelog. Split it or drop it.
2. Self-contained. Someone reading it in a year, with no other context, must
   understand it. Never write "he", "it", "this project".
   Name the repository ONLY when the fact is about that repository -- where a
   module lives, a decision about that code. When the fact is about the person,
   do NOT mention the repository at all: no "For <project>, ..." prefix and no
   trailing "in <project>". A preference is not owned by the codebase it was
   discovered in.
     BAD  "For frontend-second, prefers modal editors with tabs"
     GOOD "Prefers modal editors with tabs over separate route pages"
     BAD  "Prefers fixing data gaps on the backend rather than client shims in notiky"
     GOOD "Prefers fixing data gaps on the backend rather than with client shims"
3. Resolve relative time to absolute dates. This conversation happened on
   {session_date}; today is {today}. "last month" -> "(June 2026)".
4. Store what is true about the user and their world. Do NOT store what the
   assistant did. The assistant's turns are context only -- they are there so
   you can resolve "it" and "that project", never as source material. Prefixing
   "User implemented..." to a summary of the assistant's work does not make it
   a fact about the user.

5. All three scopes matter, and each earns its keep differently:
     scope=user     durable across every project -- preferences, identity,
                    skills, working style, tools they insist on
     scope=project  durable for the life of one codebase -- where things live,
                    architectural decisions and the reason behind them
     scope=task     only for genuinely short-lived work; these expire in days
   A window of technical work usually contains BOTH: what the user prefers in
   general, and what was decided about this codebase. Look for both. If you
   emit only project facts from a long conversation, you have probably missed
   the user's preferences hiding in how they asked for things.

6. If new information contradicts or refines a CANDIDATE, emit UPDATE with
   that candidate's id. Do not emit ADD.

7. WHAT TO LOOK FOR. Returning an empty list is legitimate, but it should be a
   conclusion, not a reflex. Read the user's turns once more and ask whether any
   of these appeared -- each is worth a memory:
     - a preference, stated or implied by a correction
       ("no, use X instead", "don't do Y", "I'd rather...")
     - an opinion about how something should look, work, or be built
     - a decision, and ideally the reason for it
     - a fact about the person: identity, contacts, location, employer, tools
     - a constraint they work under, or something they refuse to do
     - a recurring irritation or something they call out as wrong
   A correction is the single richest signal there is: when the user rejects
   something the assistant proposed, the reason behind the rejection is almost
   always a durable preference. Extract the preference, not the rejection.

8. WHAT IS NOT A MEMORY, no matter how clearly stated:
     - how the user feels right now: tired, busy, in a hurry, frustrated
     - what they are doing today, unless it outlives the week
     - a topic they asked about once ("what is tRPC?" is curiosity, not interest)
     - the assistant's own output: files touched, tests run, PRs merged
   If a window contains only these, the empty list is the right answer.

9. {credentials}

{task_status}

IMPORTANCE -- differentiate; do not cluster everything at 0.6-0.7
  0.9-1.0  identity and hard constraints, shaping almost every answer
           e.g. "Lives in Tashkent, works in Russian and English"
                "Will not run local LLMs; 16GB machine, API only"
  0.7-0.8  strong stable preferences and real skills
           e.g. "Prefers pnpm over npm in every project"
                "Writes Vue 3 with TypeScript daily; weak on Rust"
  0.4-0.6  useful but narrow: one module's location, one decision's reason
           e.g. "LMS course editor lives in a drawer, not a route page"
  0.1-0.3  weak signal, mentioned once, probably situational
  below    do not emit at all
Identity and contact details are never below 0.7. If two facts in one window get
the same importance, check that they really are equally load-bearing.

CANDIDATES (similar existing memories, may be empty)
{candidates}

CONVERSATION WINDOW
Assistant turns are truncated on purpose: they are context, not content.
{window}"""


REGISTRY: dict[str, str] = {"v2": V2, "v3": V3, "v4": V4, "v5": V5, "v6": V6}

# v6, on the argument in its WHAT CHANGED note and these numbers.
#
# Real corpus, 51 windows, paired, pooled over two runs:
#   v4  27 facts, 0.26/window,  7 user / 18 project  -> 26% reachable unscoped
#   v6  24 facts, 0.24/window, 13 user / 11 project  -> 54% reachable unscoped
# Golden set, 21 cases:
#   v4  17/18 recall, 0 false positives, 0 leaks, scope 14/14
#   v6  16/18 recall, 0 false positives, 0 leaks, scope 12/13
#
# So v6 costs a little scope precision -- one golden case sends a genuine project
# decision to user -- and roughly doubles how much of the store a query can reach
# without naming a project. That trade is taken on asymmetry, not on the margins:
# a project fact mislabelled user merely leaks into other projects' answers, where
# importance and recency still rank it down, while a user fact mislabelled project
# is dropped by the Qdrant filter and is unreachable at any rank. The second
# failure costs an order of magnitude more than the first.
#
# Every fact records the version that produced it, so this is reversible.
DEFAULT_VERSION = "v6"


# --------------------------------------------------------------------------
# Consolidator (stage 4)
# --------------------------------------------------------------------------

# Rule 4 is the load-bearing one: "Prefers pnpm" and
# "Prefers pytest" score high together because both are about tooling, and merging
# them would invent a preference the user never stated. A merge rewrites the store,
# so unlike read-path dedup a wrong call here is permanent -- returning null has to
# be an easy, explicitly blessed answer.
CONSOLIDATE_V1 = """Merge these near-duplicate memories into one.

RULES
1. Keep the most recent state of affairs. Older contradicted facts are dropped.
2. Preserve specifics: dates, names, versions, numbers.
3. The result must be shorter than the inputs combined, but must not lose
   information that is still true.
4. If the memories are actually about different things, return null for `text`.
   Similar wording is not the same as same meaning. Returning null is always
   safe; merging two distinct facts is not.
5. Keep the result under 200 characters, in the same style as the inputs.

MEMORIES
{cluster}"""

CONSOLIDATE_VERSION = "c1"


def render_cluster(facts: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- id={f['id']} type={f.get('type')} importance={f.get('importance')} "
        f"updated={f.get('updated_at')}: {f['text']}"
        for f in facts
    )


def render_consolidate(facts: list[dict[str, Any]]) -> str:
    return CONSOLIDATE_V1.format(cluster=render_cluster(facts))


def render(
    version: str,
    *,
    today: str,
    window: str,
    candidates: str,
    project: str | None = None,
    session_date: str | None = None,
    profile: str = "",
    agent_id: str | None = None,
) -> str:
    """Render a prompt version.

    Extra context arguments are ignored by versions that do not use them, so a
    caller can pass everything it has and let the version decide what matters.
    """
    template = REGISTRY.get(version)
    if template is None:
        raise ValueError(f"unknown prompt version: {version!r}")

    fields: dict[str, Any] = {
        "today": today,
        "window": window,
        "candidates": candidates,
        "examples": _WORKED_EXAMPLES,
        "credentials": _CREDENTIALS_RULE,
    }
    if version in ("v4", "v5", "v6"):
        fields["task_status"] = _TASK_STATUS_RULE
    if version in ("v3", "v4", "v5", "v6"):
        fields["context"] = render_context(
            project=project, session_date=session_date, agent_id=agent_id
        )
        fields["session_date"] = session_date or today
    if version == "v3":
        fields["profile"] = profile or "(nothing yet — this is an early conversation)"
    return template.format(**fields)


def render_context(
    *,
    project: str | None,
    session_date: str | None,
    agent_id: str | None = None,
) -> str:
    lines = []
    if project:
        lines.append(f"Project / repository: {project}")
    else:
        lines.append("Project: not identified (treat project-scoped facts with care)")
    if session_date:
        lines.append(f"Conversation date: {session_date}")
    if agent_id:
        lines.append(f"Agent the user was talking to: {agent_id}")
    return "\n".join(lines)


def render_profile(facts: list[dict[str, Any]], limit: int = 12) -> str:
    """Render the stable user profile block.

    Selected by importance rather than similarity. CANDIDATES already covers
    "facts that look like this window"; this block answers the different
    question of "who is this person", which similarity search never surfaces
    when the window happens to be about CSS.
    """
    if not facts:
        return ""
    return "\n".join(
        f"- ({f.get('type')}, importance {f.get('importance')}) {f.get('text')}"
        for f in facts[:limit]
    )
