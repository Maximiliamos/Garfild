"""Pagination, filtering and non-destructive stuck-claim detection."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from garfield_agent.storage import LocalStore


class JournalPaginationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = LocalStore(Path(temp.name) / "journal.sqlite3")
        self.now = time.time()

    def seed(self):
        # Every job has a unique composite key. SQLite sorts deterministic ties
        # by rowid, newest first.
        for index in range(9):
            workflow_id = "alpha" if index % 2 == 0 else "beta"
            key = f"file:event-{index}"
            self.assertTrue(self.store.claim_scheduled_run(workflow_id, key))
            if index % 3 == 0:
                self.store.finish_scheduled_run(workflow_id, key, False, f"err-{index}")
            elif index % 3 == 1:
                self.store.finish_scheduled_run(workflow_id, key, True, f"done-{index}")
            with self.store._lock, self.store._connect() as db:
                db.execute(
                    "UPDATE scheduled_runs SET claimed = ? WHERE workflow_id = ? AND run_key = ?",
                    (self.now + index, workflow_id, key),
                )

    def test_pages_are_ordered_without_overlap(self):
        self.seed()
        self.assertEqual(self.store.count_scheduled_runs(), 9)
        first = self.store.list_scheduled_runs(limit=4, offset=0)
        second = self.store.list_scheduled_runs(limit=4, offset=4)
        third = self.store.list_scheduled_runs(limit=4, offset=8)
        ids = [x["run_key"] for x in first + second + third]
        self.assertEqual(ids, [f"file:event-{i}" for i in reversed(range(9))])
        self.assertEqual(len(set(ids)), 9)
        self.assertEqual(len(self.store.list_scheduled_runs(limit=4, offset=99)), 0)

    def test_combined_exact_status_and_workflow_filters(self):
        self.seed()
        self.assertEqual(self.store.count_scheduled_runs(status="failed"), 3)
        self.assertEqual(self.store.count_scheduled_runs(workflow_id="alpha"), 5)
        self.assertEqual(
            self.store.count_scheduled_runs(status="failed", workflow_id="alpha"), 2
        )
        rows = self.store.list_scheduled_runs(
            limit=10, status="failed", workflow_id="alpha"
        )
        self.assertEqual({row["run_key"] for row in rows}, {"file:event-0", "file:event-6"})
        self.assertEqual(self.store.count_scheduled_runs(workflow_id="missing"), 0)

    def test_filters_reject_invalid_values(self):
        with self.assertRaises(ValueError):
            self.store.count_scheduled_runs(status="all OR 1=1")
        with self.assertRaises(ValueError):
            self.store.count_scheduled_runs(workflow_id="alpha'--")
        with self.assertRaises(ValueError):
            self.store.list_scheduled_runs(limit=0)
        with self.assertRaises(ValueError):
            self.store.list_scheduled_runs(limit=201)
        with self.assertRaises(ValueError):
            self.store.list_scheduled_runs(offset=-1)
        with self.assertRaises(ValueError):
            self.store.list_scheduled_runs(offset=100_001)

    def test_old_claim_is_flagged_but_not_rescheduled_or_failed(self):
        self.assertTrue(self.store.claim_scheduled_run("alpha", "daily:2026-11-02:09:00"))
        with self.store._lock, self.store._connect() as db:
            db.execute(
                "UPDATE scheduled_runs SET claimed = ?, heartbeat = ? "
                "WHERE workflow_id = 'alpha'",
                (self.now - 3600, self.now - 3600),
            )
        old = self.store.list_scheduled_runs(now=self.now)[0]
        self.assertTrue(old["needs_review"])
        self.assertEqual(old["status"], "claimed")
        self.assertEqual(
            self.store.scheduled_run_status("alpha", "daily:2026-11-02:09:00"),
            "claimed",
        )
        # An old in-progress record must not be changed merely by reading.
        self.assertFalse(
            self.store.claim_scheduled_run("alpha", "daily:2026-11-02:09:00")
        )
        fresh = self.store.list_scheduled_runs(now=self.now - 3500)[0]
        self.assertFalse(fresh["needs_review"])

    def test_non_claimed_runs_are_never_flagged(self):
        self.store.claim_scheduled_run("alpha", "file:old")
        self.store.finish_scheduled_run("alpha", "file:old", False, "error")
        with self.store._lock, self.store._connect() as db:
            db.execute("UPDATE scheduled_runs SET claimed = ?", (self.now - 86400,))
        self.assertFalse(self.store.list_scheduled_runs(now=self.now)[0]["needs_review"])


if __name__ == "__main__":
    unittest.main()
