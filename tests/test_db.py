"""Connection handling.

The interesting property here is not that SQLite works, it is that two threads
writing at once cannot corrupt each other's unit of work. `transaction()` commits
the *connection*, so a connection shared between writing threads means one
thread's COMMIT persists another's half-finished write and one thread's ROLLBACK
throws it away. FastAPI runs every sync endpoint in a threadpool and runs
background extraction alongside them, so this is the normal case.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit.db import ConnectionPool, connect, init_db, transaction


def make_pool() -> ConnectionPool:
    path = Path(tempfile.mkdtemp()) / "t.db"
    init_db(path)
    return ConnectionPool(path)


class TestConnectionPool(unittest.TestCase):
    def test_same_thread_gets_one_connection(self):
        pool = make_pool()
        self.assertIs(pool(), pool())

    def test_each_thread_gets_its_own(self):
        pool = make_pool()
        seen: list[int] = []
        barrier = threading.Barrier(3)

        def grab() -> None:
            barrier.wait()
            seen.append(id(pool()))

        threads = [threading.Thread(target=grab) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(seen)), 3)

    def test_a_rollback_in_one_thread_keeps_another_threads_write(self):
        """The failure the pool exists to prevent.

        On a shared connection the rollback below would also discard the row the
        other thread had already committed, because ROLLBACK acts on the
        connection and not on the block.
        """
        pool = make_pool()
        with transaction(pool()) as conn:
            conn.execute("INSERT INTO owners (id, name, created_at) VALUES ('keep','k','t')")

        def failing_write() -> None:
            with self.assertRaises(RuntimeError), transaction(pool()) as conn:
                conn.execute("INSERT INTO owners (id, name, created_at) VALUES ('drop','d','t')")
                raise RuntimeError("boom")

        thread = threading.Thread(target=failing_write)
        thread.start()
        thread.join()

        rows = {row["id"] for row in pool().execute("SELECT id FROM owners")}
        self.assertEqual(rows, {"keep"})

    def test_close_all_is_idempotent_and_reopens_after(self):
        pool = make_pool()
        first = pool()
        pool.close_all()
        pool.close_all()
        second = pool()
        self.assertIsNot(first, second)
        # Usable again, not just a fresh object.
        second.execute("SELECT COUNT(*) FROM owners").fetchone()


class TestSchemaGuard(unittest.TestCase):
    def test_a_newer_schema_refuses_to_open(self):
        path = Path(tempfile.mkdtemp()) / "t.db"
        init_db(path)
        conn = connect(path)
        conn.execute("PRAGMA user_version=99")
        conn.commit()
        conn.close()
        with self.assertRaises(RuntimeError):
            init_db(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
