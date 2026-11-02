import tempfile
import unittest
from pathlib import Path
from garfield_agent.updates import UpdateManager


class FakeUpdater(UpdateManager):
    def __init__(self, root):
        super().__init__(root)
        self.calls = []
        self.remote = "a" * 40
        self.dirty = False
        self.branch = "main"
        self.ahead = "0\t2"

    def _git(self, *args):
        self.calls.append(args)
        if args == ("remote", "get-url", "origin"):
            return "https://github.com/Maximiliamos/Garfild.git"
        if args == ("branch", "--show-current"):
            return self.branch
        if args == ("status", "--porcelain"):
            return " M bad.py" if self.dirty else ""
        if args == ("rev-parse", "FETCH_HEAD"):
            return self.remote
        if args == ("rev-list", "--left-right", "--count", "HEAD...FETCH_HEAD"):
            return self.ahead
        return ""


class UpdateTests(unittest.TestCase):
    def test_requires_confirmation_before_merge(self):
        with tempfile.TemporaryDirectory() as path:
            updater = FakeUpdater(Path(path))
            self.assertIn("Обнаружено", updater.check())
            self.assertNotIn(("merge", "--ff-only", "FETCH_HEAD"), updater.calls)
            self.assertIn("перезапустите", updater.apply())
            self.assertIn(("merge", "--ff-only", "FETCH_HEAD"), updater.calls)

    def test_blocks_dirty_branch_and_divergence(self):
        with tempfile.TemporaryDirectory() as path:
            updater = FakeUpdater(Path(path))
            updater.dirty = True
            with self.assertRaises(RuntimeError):
                updater.check()
            updater.dirty = False
            updater.branch = "feature"
            with self.assertRaises(RuntimeError):
                updater.check()
            updater.branch = "main"
            updater.ahead = "1\t2"
            self.assertIn("заблокировано", updater.check())
            self.assertIsNone(updater.pending_sha)


if __name__ == "__main__":
    unittest.main()
