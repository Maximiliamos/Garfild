"""Regression: opt-in SQLite saves must not create plaintext transcript on shutdown."""
import ast
import pathlib
import unittest


class PrivacyTests(unittest.TestCase):
    def test_runtime_stop_never_writes_plaintext_transcript(self):
        path = pathlib.Path(__file__).resolve().parents[1] / "garfield_flagship.py"
        module = ast.parse(path.read_text(encoding="utf-8"))
        runtime = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "FlagshipRuntime")
        stop = next(n for n in runtime.body if isinstance(n, ast.FunctionDef) and n.name == "stop")
        calls = [
            n.func.attr for n in ast.walk(stop)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        self.assertNotIn("_save_session_history", calls)

    def test_export_is_still_available_on_explicit_request(self):
        path = pathlib.Path(__file__).resolve().parents[1] / "garfield_flagship.py"
        module = ast.parse(path.read_text(encoding="utf-8"))
        runtime = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "FlagshipRuntime")
        self.assertTrue(any(
            isinstance(n, ast.FunctionDef) and n.name == "_save_session_history"
            for n in runtime.body
        ))


if __name__ == "__main__":
    unittest.main()
