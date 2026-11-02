import unittest
from garfield_agent.model_manager import ModelManager


class ModelTests(unittest.TestCase):
    def test_download_needs_explicit_confirmation(self):
        manager = ModelManager()
        with self.assertRaises(ValueError):
            manager.prepare("unexpected_model:latest")
        self.assertIsNone(manager.pending)
        self.assertIn("подтверди загрузку", manager.prepare("qwen2.5:3b"))
        self.assertEqual(manager.pending, "qwen2.5:3b")
        self.assertIn("отменена", manager.cancel())
        self.assertIn("не подтверждена", manager.confirm())


if __name__ == "__main__":
    unittest.main()
