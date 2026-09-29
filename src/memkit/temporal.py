"""Time as data: event dates on memories, and time windows in queries.

Two different dates describe one memory, and conflating them is the classic
temporal-reasoning failure:

    document_date   when the claim was said or written -- the anchor every
                    relative phrase in it was resolved against;
    event_dates     when the thing it describes happened or will happen.

"On Tuesday I told you I'd moved to Lisbon in March" has a document date of
that Tuesday and an event date of March. A question asking "when did I move?"
wants the second; "what did I tell you last week?" wants the first.

Event dates keep the granularity the speaker gave -- `2026`, `2026-03`, or
`2026-03-14` -- because inventing a day for "in March" is how a memory system
answers "March 1st" with confidence. `interval` turns any set of them into the
bounding range the database indexes.

Query parsing is deliberately rule-based and bilingual (English and Russian,
the two languages this corpus is written in). It recognises the phrases that
carry an unambiguous window -- "yesterday", "last month", "в прошлом году",
"in May 2025", "3 weeks ago" -- and says nothing about anything else. A wrong
window would boost the wrong facts, so an unrecognised phrase yields no window
rather than a guess.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

_GRANULAR = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
MAX_EVENT_DATES = 8


def _period(value: str) -> tuple[date, date] | None:
    """The first and last day a granular date string covers, or None."""
    match = _GRANULAR.match(value)
    if match is None:
        return None
    year = int(match.group(1))
    if not 1900 <= year <= 2200:
        return None
    try:
        if match.group(3):
            day = date(year, int(match.group(2)), int(match.group(3)))
            return day, day
        if match.group(2):
            month = int(match.group(2))
            last = calendar.monthrange(year, month)[1]
            return date(year, month, 1), date(year, month, last)
    except ValueError:
        return None
    return date(year, 1, 1), date(year, 12, 31)


def normalize_event_date(value: object) -> str | None:
    """One event date in canonical granular form, or None if it is not one.

    Accepts the three granularities and a full ISO timestamp (cut to its day),
    which is what a model returns when it over-specifies.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "T" in text or " " in text:
        text = text.replace(" ", "T").split("T", 1)[0]
    return text if _period(text) is not None else None


def normalize_event_dates(values: Iterable[object] | None) -> list[str]:
    """Canonical, de-duplicated, sorted event dates; invalid entries dropped."""
    seen: dict[str, None] = {}
    for value in values or ():
        normalized = normalize_event_date(value)
        if normalized is not None:
            seen.setdefault(normalized, None)
    return sorted(seen)[:MAX_EVENT_DATES]


def interval(values: Iterable[str]) -> tuple[datetime | None, datetime | None]:
    """The bounding UTC interval of canonical event dates, end inclusive."""
    periods = [p for p in (_period(v) for v in values) if p is not None]
    if not periods:
        return None, None
    start = min(p[0] for p in periods)
    end = max(p[1] for p in periods)
    return (
        datetime(start.year, start.month, start.day, tzinfo=UTC),
        datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC),
    )


@dataclass(frozen=True)
class TimeWindow:
    """An inclusive UTC window a query refers to, and how it was recognised."""

    start: datetime
    end: datetime
    phrase: str

    def overlaps(self, start: datetime | None, end: datetime | None) -> bool:
        lo = start or end
        hi = end or start
        if lo is None or hi is None:
            return False
        return lo <= self.end and hi >= self.start

    def as_dict(self) -> dict[str, str]:
        return {
            "start": self.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": self.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "phrase": self.phrase,
        }


@dataclass(frozen=True)
class TemporalIntent:
    """What a query says about time: a window, an ordering, or both."""

    window: TimeWindow | None = None
    # "first", "earliest" -> "earliest"; "latest", "most recent", "last time",
    # "currently", "now" -> "latest". None when the query expresses neither.
    order: str | None = None
    # True when the question is about time at all ("when", "how long", "how
    # many days"): dates should accompany the answer even without a window.
    asks_time: bool = False

    @property
    def active(self) -> bool:
        return self.window is not None or self.order is not None or self.asks_time


def _day_window(day: date, phrase: str) -> TimeWindow:
    return TimeWindow(
        datetime(day.year, day.month, day.day, tzinfo=UTC),
        datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=UTC),
        phrase,
    )


def _span(first: date, last: date, phrase: str) -> TimeWindow:
    return TimeWindow(
        datetime(first.year, first.month, first.day, tzinfo=UTC),
        datetime(last.year, last.month, last.day, 23, 59, 59, tzinfo=UTC),
        phrase,
    )


def _month_span(year: int, month: int, phrase: str) -> TimeWindow:
    return _span(
        date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]), phrase
    )


def _shift_month(day: date, months: int) -> tuple[int, int]:
    index = day.year * 12 + (day.month - 1) + months
    return index // 12, index % 12 + 1


_EN_MONTHS = {
    **{name.lower(): i for i, name in enumerate(calendar.month_name) if name},
    **{name.lower(): i for i, name in enumerate(calendar.month_abbr) if name},
    "sept": 9,
}
# Russian stems cover every case form (январь/января/январе). Order matters:
# "март" must be tried before "ма", which is May's stem.
_RU_MONTHS = (
    ("январ", 1),
    ("феврал", 2),
    ("март", 3),
    ("апрел", 4),
    ("ма", 5),
    ("июн", 6),
    ("июл", 7),
    ("август", 8),
    ("сентябр", 9),
    ("октябр", 10),
    ("ноябр", 11),
    ("декабр", 12),
)
_RU_MONTH = re.compile(
    r"\b(январ[ьяе]|феврал[ьяе]|март[ае]?|апрел[ьяе]|ма[йяе]|июн[ьяе]|июл[ьяе]|"
    r"август[ае]?|сентябр[ьяе]|октябр[ьяе]|ноябр[ьяе]|декабр[ьяе])\b(?:\s+(\d{4}))?",
    re.IGNORECASE,
)
_EN_MONTH = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|"
    r"december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b\.?(?:,?\s+(\d{4}))?",
    re.IGNORECASE,
)
_ISO_DAY = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_ISO_MONTH = re.compile(r"\b(\d{4})-(\d{2})\b(?!-)")
_YEAR = re.compile(r"\b(?:in|during|since|в|во|за)\s+(\d{4})(?:\s*(?:году|г\.?))?\b", re.IGNORECASE)
_AGO = re.compile(
    r"\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(day|days|week|weeks|month|months|year|years)\s+ago\b",
    re.IGNORECASE,
)
_RU_AGO = re.compile(
    r"\b(\d+)\s+(день|дня|дней|недел[юиь]|месяц|месяца|месяцев|год|года|лет)\s+назад\b",
    re.IGNORECASE,
)
_WORD_NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_LATEST = re.compile(
    r"\b(latest|most recent(?:ly)?|last time|currently|current|now|these days|"
    r"сейчас|теперь|последн\w*|в последний раз|текущ\w*)\b",
    re.IGNORECASE,
)
_EARLIEST = re.compile(
    r"\b(first|earliest|initially|originally|at first|впервые|сначала|перв\w*|изначально)\b",
    re.IGNORECASE,
)
_ASKS_TIME = re.compile(
    r"\b(when|what date|which day|how long|how many (?:days|weeks|months|years)|"
    r"before|after|since|until|ago|когда|какого числа|сколько (?:дней|недель|месяцев|лет)|"
    r"до того|после того|давно)\b",
    re.IGNORECASE,
)


def _relative_window(text: str, today: date) -> TimeWindow | None:
    lowered = text.casefold()
    week_start = today - timedelta(days=today.weekday())
    if re.search(r"\b(the day before yesterday|позавчера)\b", lowered):
        return _day_window(today - timedelta(days=2), "day before yesterday")
    if re.search(r"\b(yesterday|вчера)\b", lowered):
        return _day_window(today - timedelta(days=1), "yesterday")
    if re.search(r"\b(today|tonight|this morning|сегодня)\b", lowered):
        return _day_window(today, "today")
    if re.search(r"\b(last|past|previous) week\b|прошлой неделе", lowered):
        start = week_start - timedelta(days=7)
        return _span(start, start + timedelta(days=6), "last week")
    if re.search(r"\bthis week\b|этой неделе", lowered):
        return _span(week_start, today, "this week")
    if re.search(r"\b(last|past|previous) month\b|прошлом месяце", lowered):
        year, month = _shift_month(today, -1)
        return _month_span(year, month, "last month")
    if re.search(r"\bthis month\b|этом месяце", lowered):
        return _span(today.replace(day=1), today, "this month")
    if re.search(r"\b(last|past|previous) year\b|прошлом году", lowered):
        year = today.year - 1
        return _span(date(year, 1, 1), date(year, 12, 31), "last year")
    if re.search(r"\bthis year\b|этом году", lowered):
        return _span(date(today.year, 1, 1), today, "this year")
    if re.search(r"\b(recently|lately)\b|недавно", lowered):
        return _span(today - timedelta(days=30), today, "recently")
    match = _AGO.search(lowered)
    if match:
        amount = _WORD_NUMBERS.get(match.group(1)) or int(match.group(1))
        unit = match.group(2).rstrip("s")
        return _ago(today, amount, unit, match.group(0))
    match = _RU_AGO.search(lowered)
    if match:
        unit_word = match.group(2)
        unit = (
            "day"
            if unit_word.startswith(("д", "дн"))
            else "week"
            if unit_word.startswith("недел")
            else "month"
            if unit_word.startswith("месяц")
            else "year"
        )
        return _ago(today, int(match.group(1)), unit, match.group(0))
    return None


def _ago(today: date, amount: int, unit: str, phrase: str) -> TimeWindow | None:
    if amount <= 0 or amount > 1000:
        return None
    if unit == "day":
        return _day_window(today - timedelta(days=amount), phrase)
    if unit == "week":
        center = today - timedelta(weeks=amount)
        return _span(center - timedelta(days=3), center + timedelta(days=3), phrase)
    if unit == "month":
        year, month = _shift_month(today, -amount)
        return _month_span(year, month, phrase)
    year = today.year - amount
    return _span(date(year, 1, 1), date(year, 12, 31), phrase) if year >= 1900 else None


def _absolute_window(text: str, today: date) -> TimeWindow | None:
    match = _ISO_DAY.search(text)
    if match:
        try:
            return _day_window(
                date(int(match.group(1)), int(match.group(2)), int(match.group(3))), match.group(0)
            )
        except ValueError:
            return None
    match = _ISO_MONTH.search(text)
    if match and 1 <= int(match.group(2)) <= 12:
        return _month_span(int(match.group(1)), int(match.group(2)), match.group(0))
    for pattern, russian in ((_EN_MONTH, False), (_RU_MONTH, True)):
        match = pattern.search(text)
        if match is None:
            continue
        word = match.group(1).casefold().rstrip(".")
        # "may" is also a modal verb; only a year or a preposition makes it a month.
        if word == "may" and not match.group(2):
            before = text[: match.start()].casefold().rstrip()
            if not re.search(r"\b(in|during|since|until|of|early|late|mid)$", before):
                continue
        if russian:
            month = next((number for stem, number in _RU_MONTHS if word.startswith(stem)), None)
        else:
            month = _EN_MONTHS.get(word)
        if month is None:
            continue
        if match.group(2):
            year = int(match.group(2))
        else:
            # A bare month means its most recent occurrence not after today.
            year = today.year if month <= today.month else today.year - 1
        return _month_span(year, month, match.group(0))
    match = _YEAR.search(text)
    if match:
        year = int(match.group(1))
        if 1900 <= year <= 2200:
            return _span(date(year, 1, 1), date(year, 12, 31), match.group(0))
    return None


def parse_intent(query: str, *, now: datetime | None = None) -> TemporalIntent:
    """What the query says about time, relative to `now` (the question date).

    `now` matters for every benchmark and backfill: "last month" asked in a
    conversation recorded in 2023 means 2023's last month, not today's.
    """
    reference = (now or datetime.now(UTC)).astimezone(UTC).date()
    window = _relative_window(query, reference) or _absolute_window(query, reference)
    order = None
    if _EARLIEST.search(query):
        order = "earliest"
    elif _LATEST.search(query):
        order = "latest"
    asks = bool(_ASKS_TIME.search(query)) or window is not None
    return TemporalIntent(window=window, order=order, asks_time=asks)


def render_date(value: datetime | str | None) -> str | None:
    """A compact YYYY-MM-DD for context rendering."""
    if value is None:
        return None
    if isinstance(value, str):
        return value[:10] or None
    return value.astimezone(UTC).strftime("%Y-%m-%d")
