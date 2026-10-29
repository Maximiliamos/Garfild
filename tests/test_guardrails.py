"""Regression checks that run without audio devices or paid API credentials."""
import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ast.parse((ROOT / "garfield_best.py").read_text(encoding="utf-8"))
APP = ast.parse((ROOT / "garfield_flagship.py").read_text(encoding="utf-8"))

def method(module, klass, name):
    cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == klass)
    return next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)

class GuardrailTests(unittest.TestCase):
    def test_exit_requires_exact_command(self):
        fn = method(CORE, "AssistantCore", "_handle_builtin_command")
        first = fn.body[0]
        self.assertIsInstance(first, ast.If)
        self.assertIsInstance(first.test, ast.Compare)
        self.assertIn("пока", ast.literal_eval(first.test.comparators[0]))
        self.assertNotIn("покажи список команд", ast.literal_eval(first.test.comparators[0]))

    def test_grok_maps_to_xai(self):
        fn = next(n for n in CORE.body if isinstance(n, ast.FunctionDef) and n.name == "normalize_llm_provider")
        assignments = [n for n in fn.body if isinstance(n, ast.Assign)]
        aliases = ast.literal_eval(next(n.value for n in assignments if any(isinstance(t, ast.Name) and t.id == "aliases" for t in n.targets)))
        self.assertEqual(aliases["grok"], "xai")

    def test_shell_execution_disabled(self):
        fn = method(CORE, "SkillRegistry", "execute")
        source = ast.unparse(fn)
        self.assertNotIn("shell=True", source)
        self.assertIn("PermissionError", source)

    def test_runtime_always_acknowledges_queued_command(self):
        fn = method(APP, "FlagshipRuntime", "_command_worker_loop")
        finally_blocks = [n.finalbody for n in ast.walk(fn) if isinstance(n, ast.Try)]
        self.assertTrue(any("self.command_queue.task_done()" in ast.unparse(b) for b in finally_blocks))

    def test_cache_key_includes_history_and_model(self):
        source = ast.unparse(method(CORE, "AssistantCore", "_ask_llm_or_fallback"))
        self.assertIn("self.history.as_messages()", source)
        self.assertIn("self.llm_client.model", source)
        self.assertIn("time.monotonic()", source)

if __name__ == "__main__":
    unittest.main()
