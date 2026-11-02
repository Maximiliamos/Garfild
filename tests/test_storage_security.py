import os
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from garfield_agent.storage import LocalStore


class LocalStoreSecurityTests(unittest.TestCase):
    def test_windows_persisted_rows_are_sealed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "local.sqlite3"
            store = LocalStore(path)
            store.add_note("частная заметка секрет")
            store.add_message("user", "это личный разговор")
            store.record_run([{"tool": "system_status"}], [{"status": "ok"}])
            with closing(sqlite3.connect(path)) as db:
                raw_note = db.execute("SELECT content FROM notes").fetchone()[0]
                raw_message = db.execute("SELECT text FROM conversations").fetchone()[0]
                raw_run = db.execute("SELECT plan FROM executions").fetchone()[0]
            if os.name == "nt":
                for record in (raw_note, raw_message, raw_run):
                    self.assertTrue(record.startswith("dpapi:"))
                self.assertNotIn("секрет", raw_note)
            else:
                self.assertIn("секрет", raw_note)
            self.assertIn("частная", store.notes("частная")[0]["content"])
            self.assertIn("личный", store.search_messages("личный")[0]["text"])

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_plaintext_legacy_is_migrated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite3"
            LocalStore(path)
            with closing(sqlite3.connect(path)) as db:
                db.execute("INSERT INTO notes(created, content) VALUES (0, ?)", ("legacy secret",))
                db.commit()
            new = LocalStore(path)
            self.assertIn("legacy secret", new.notes()[0]["content"])
            with closing(sqlite3.connect(path)) as db:
                raw = db.execute("SELECT content FROM notes").fetchone()[0]
            self.assertTrue(raw.startswith("dpapi:"))


if __name__ == "__main__":
    unittest.main()
