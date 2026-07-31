"""Admin list-query correctness, especially Unicode and stable pagination."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import HTTPException  # noqa: E402
from memkit import admin  # noqa: E402
from memkit.db import utcnow  # noqa: E402
from tests.fixtures import OWNER, make_db  # noqa: E402


class TestAdminQueries(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def add(self, memory_id: str, text: str, updated: str = "2026-07-01T00:00:00Z"):
        self.conn.execute(
            """INSERT INTO memories
               (id,owner_id,scope,type,text,importance,confidence,status,
                valid_from,created_at,updated_at,extraction_version)
               VALUES(?,?,'user','fact',?,.5,.9,'active',?,?,?,'manual')""",
            (memory_id, OWNER, text, updated, updated, updated),
        )

    def test_cyrillic_casefold_and_literal_wildcards(self):
        self.add("a", "Предпочитает pnpm")
        self.add("b", "100% literal_under_score")
        self.conn.commit()
        found = admin.list_memories_data(
            self.conn, owner_id=OWNER, q="ПРЕДПОЧИТАЕТ"
        )
        self.assertEqual([row["id"] for row in found["memories"]], ["a"])
        literal = admin.list_memories_data(
            self.conn, owner_id=OWNER, q="% literal_"
        )
        self.assertEqual([row["id"] for row in literal["memories"]], ["b"])

    def test_offset_pagination_has_id_tiebreak(self):
        for index in range(30):
            self.add(f"{index:02}", f"fact {index}")
        self.conn.commit()
        ids = []
        for offset in (0, 10, 20):
            page = admin.list_memories_data(
                self.conn, owner_id=OWNER, limit=10, offset=offset
            )
            ids.extend(row["id"] for row in page["memories"])
        self.assertEqual(ids, [f"{index:02}" for index in range(30)])
        self.assertEqual(len(set(ids)), 30)

    def test_unknown_sort_never_reaches_sql(self):
        with self.assertRaises(HTTPException) as caught:
            admin.list_memories_data(
                self.conn, owner_id=OWNER, sort="updated_at; DROP TABLE memories"
            )
        self.assertEqual(caught.exception.status_code, 422)
        self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()

    def test_analytics_summary_is_zero_filled_and_bucketed(self):
        self.add("fresh", "Fresh fact", updated=utcnow())
        self.conn.commit()
        summary = admin.analytics_summary(self.conn, owner_id=OWNER, days=7)
        self.assertEqual(len(summary["daily"]), 7)
        self.assertEqual(sum(item["memories"] for item in summary["daily"]), 1)
        self.assertEqual(summary["confidence"]["high"], 1)
        self.assertEqual(summary["retrieval"]["never"], 1)

    def test_yearly_activity_is_zero_filled_and_chronological(self):
        self.add("today", "Today", updated=utcnow())
        self.conn.commit()
        activity = admin.daily_activity(self.conn, owner_id=OWNER, days=365)
        self.assertEqual(len(activity), 365)
        self.assertLess(activity[0]["day"], activity[-1]["day"])
        self.assertEqual(sum(day["memories"] for day in activity), 1)
        self.assertEqual(
            sum(day["memory_types"].get("fact", 0) for day in activity),
            1,
        )
        self.assertEqual(
            set(activity[-1]),
            {
                "day",
                "memories",
                "memory_types",
                "messages",
                "judge_runs",
                "cost_usd",
            },
        )


if __name__ == "__main__":
    unittest.main()
