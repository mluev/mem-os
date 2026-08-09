"""Where a stored fact came from, and what may be stored at all.

The closed loop this exists to break: a model asserts something, the assertion
becomes a memory, the memory is prefetched into the next prompt, the model reads
its own claim back as established fact and restates it with more confidence. Once
that starts there is no way to find the beginning of it, because the memory looks
exactly like one the user stated.

The extractor prompt does ask for this ("the assistant's turns are context only,
never source material"), and a prompt rule is a request, not a guarantee. This is
the guarantee: a column no writer can omit, and a predicate at the write itself.

Honest scope, because the value of a guard is exactly what it catches:

* On the **extraction path** `may_write` cannot currently fire. `apply_ops` links
  the whole window to every fact it creates, and `fast_forward_to_user_turn`
  guarantees each window holds a user turn, so the roles are always
  ``{user, assistant}``. It is a fail-closed regression detector there -- it
  starts doing real work the day the judge cites its own evidence per operation,
  or the day someone narrows the window for cost.
* On the **API path** the column is load-bearing today. Two Hermes features write
  model-authored text straight past the judge: ``on_memory_write`` at importance
  0.8 and the ``memkit_remember`` tool at 0.9. Before this column they landed as
  ``extraction_version='manual'``, indistinguishable from something the user
  typed. Measured on the live store the day this was written: of eight facts
  added in one session, seven were model-authored, including the same claim
  written four times at 0.8-0.95.

See decisions/0006 for the decision and decisions/0007 for why refusals are
logged where they are rather than into an events journal.
"""

from __future__ import annotations

import sqlite3

# The vocabulary from the original spec, kept verbatim so an archived document
# and a live column mean the same thing.
ROLES: tuple[str, ...] = ("user", "assistant", "agent", "tool", "manual")

# Authority order, highest first. A window containing one user turn is sourced by
# the user regardless of how much assistant text surrounds it -- the assistant's
# words are the context that made the user's turn legible, not the claim.
#
# 'tool' is unreachable today: MessageIn.role is Literal["user","assistant"] and
# the transcript importer emits only those two. It stays in the vocabulary so a
# tool-output ingest path is a code change and not a migration.
_AUTHORITY: tuple[str, ...] = ("user", "tool", "assistant", "agent")

DEFAULT_ROLE = "manual"

# Reason string for a refused write. Matches the action name the archived spec
# gave its rejection event, so the log line and that document are greppable
# together even though the events table was never built.
REJECTED_ASSISTANT_ONLY = "assistant_only_source"


def roles_of(conn: sqlite3.Connection, message_ids: list[int] | None) -> set[str]:
    """The distinct roles of the messages a write cites. One query."""
    if not message_ids:
        return set()
    placeholders = ",".join("?" * len(message_ids))
    rows = conn.execute(
        f"SELECT DISTINCT role FROM messages WHERE id IN ({placeholders})",
        tuple(message_ids),
    ).fetchall()
    return {row["role"] for row in rows}


def source_role_for(roles: set[str]) -> str:
    """Collapse a set of evidence roles to the single authority label.

    Empty evidence is ``'manual'``: the authority is then the caller holding the
    API key, not a message, and the label should say so rather than guess.
    """
    for role in _AUTHORITY:
        if role in roles:
            return role
    return DEFAULT_ROLE


# Trust order for *combining* facts, weakest first. Not the reverse of
# _AUTHORITY: 'manual' sits above 'assistant' but below 'user' on purpose.
# 'manual' means an API-key holder asserted it with no message behind it, which
# is weaker evidence than a user turn and stronger than a model's own sentence.
_WEAKEST_FIRST: tuple[str, ...] = ("agent", "assistant", "manual", "tool", "user")


def weakest(roles: set[str]) -> str:
    """The least-trusted label in a set, for a fact derived from several others.

    Consolidation merges N facts into one whose text carries content from all of
    them, so the survivor is no better sourced than its worst input. Taking the
    newest member's label instead would let a merge launder an assistant-sourced
    sentence into a user-sourced fact -- and a merge is permanent where a bad
    search result is not.
    """
    for role in _WEAKEST_FIRST:
        if role in roles:
            return role
    return DEFAULT_ROLE


def may_write(*, op: str, roles: set[str]) -> bool:
    """False when a write's only evidence is the assistant's own words.

    Two deliberate exemptions:

    ``DELETE`` -- removing a fact injects no content, and refusing it would keep
    a bad fact alive on the grounds that the wrong party noticed it.

    Empty evidence -- authority comes from the caller, and `source_role_for`
    labels it ``'manual'`` so it stays visible. The archived predicate was
    ``roles <= {"assistant"}``, which is True for the empty set; restored
    verbatim it rejects every write that cites nothing, including seventeen of
    the nineteen ``apply()`` calls in this repo's own test suite. The ``not
    roles`` clause is a bug fix, not a loosening.
    """
    if op == "DELETE" or not roles:
        return True
    return not roles <= {"assistant", "agent"}


def validate(source_role: str) -> str:
    """Reject an out-of-vocabulary label at the boundary.

    `scope` was silently accepting anything until it was pinned; a provenance
    column that can hold 'assistnat' proves nothing at all.
    """
    if source_role not in ROLES:
        raise ValueError(f"invalid source_role {source_role!r}; expected one of {', '.join(ROLES)}")
    return source_role
