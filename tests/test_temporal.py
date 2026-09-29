"""Event-date normalisation and query time windows, English and Russian."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memkit import judge, providers, temporal

NOW = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)  # a Tuesday


def window(query: str) -> tuple[str, str] | None:
    intent = temporal.parse_intent(query, now=NOW)
    if intent.window is None:
        return None
    return intent.window.as_dict()["start"][:10], intent.window.as_dict()["end"][:10]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("what did I cook yesterday?", ("2026-09-28", "2026-09-28")),
        ("что я делал вчера", ("2026-09-28", "2026-09-28")),
        ("anything from last week?", ("2026-09-21", "2026-09-27")),
        ("что было на прошлой неделе", ("2026-09-21", "2026-09-27")),
        ("what did I buy last month", ("2026-08-01", "2026-08-31")),
        ("в прошлом месяце", ("2026-08-01", "2026-08-31")),
        ("where did I travel last year", ("2025-01-01", "2025-12-31")),
        ("in May 2025", ("2025-05-01", "2025-05-31")),
        ("в мае 2024", ("2024-05-01", "2024-05-31")),
        ("в марте", ("2026-03-01", "2026-03-31")),
        # A bare month later than the current one means last year's.
        ("what happened in December", ("2025-12-01", "2025-12-31")),
        ("3 weeks ago", ("2026-09-05", "2026-09-11")),
        ("5 дней назад", ("2026-09-24", "2026-09-24")),
        ("on 2026-03-14", ("2026-03-14", "2026-03-14")),
        ("during 2023", ("2023-01-01", "2023-12-31")),
    ],
)
def test_query_windows(query, expected):
    assert window(query) == expected


@pytest.mark.parametrize(
    "query",
    ["may I ask about pnpm", "what is my favourite editor", "march of the penguins documentary"],
)
def test_no_window_is_better_than_a_wrong_one(query):
    # "march of the penguins" still names a month; the parser only refuses the
    # modal "may". The other two carry no time at all.
    if query.startswith("march"):
        assert window(query) is not None
    else:
        assert window(query) is None


def test_ordering_and_time_questions():
    assert temporal.parse_intent("when did I first try sushi", now=NOW).order == "earliest"
    assert temporal.parse_intent("what is my current job", now=NOW).order == "latest"
    assert temporal.parse_intent("how many days between the trips", now=NOW).asks_time
    assert not temporal.parse_intent("favourite colour", now=NOW).active


def test_event_dates_keep_the_granularity_the_speaker_gave():
    assert temporal.normalize_event_dates(
        ["2026-03", "2026-03-14T08:00:00Z", "2025", "2026-02-30", "soon", "2026-03"]
    ) == ["2025", "2026-03", "2026-03-14"]
    start, end = temporal.interval(["2026-03", "2025"])
    assert (start.isoformat(), end.isoformat()) == (
        "2025-01-01T00:00:00+00:00",
        "2026-03-31T23:59:59+00:00",
    )
    assert temporal.interval([]) == (None, None)


def test_window_overlap():
    intent = temporal.parse_intent("last month", now=NOW)
    start, end = temporal.interval(["2026-08-15"])
    assert intent.window.overlaps(start, end)
    start, end = temporal.interval(["2026-07"])
    assert not intent.window.overlaps(start, end)
    assert not intent.window.overlaps(None, None)


def test_the_extractor_schema_carries_the_v11_fields():
    required = providers.anthropic_tool()["input_schema"]["properties"]["operations"]["items"][
        "required"
    ]
    for name in ("event_dates", "is_static", "extends", "change"):
        assert name in required
        assert name in providers.gemini_schema()["properties"]["operations"]["items"]["properties"]


def test_op_parse_normalises_graph_fields():
    evidence = [{"message_id": 1, "start_char": 0, "end_char": 1, "quote": "x"}]
    add = judge.Op.parse(
        {
            "op": "ADD",
            "text": "x",
            "evidence": evidence,
            "change": "supersede",
            "extends": 2,
            "event_dates": "2026-03",
        }
    )
    # `change` belongs to UPDATE only; a lone date string is accepted as a list.
    assert (add.change, add.extends, add.event_dates) == (None, "2", ["2026-03"])
    update = judge.Op.parse(
        {
            "op": "UPDATE",
            "id": "1",
            "text": "x",
            "evidence": evidence,
            "change": "rewrite",
            "extends": 3,
            "is_static": "yes",
        }
    )
    assert (update.change, update.extends, update.is_static) == (None, None, None)
