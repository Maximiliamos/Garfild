import unittest
from garfield_agent.workflow_editor import move_step, replace_step, delete_step


class WorkflowEditorTests(unittest.TestCase):
    def setUp(self):
        self.steps = [{"tool": "a", "args": {}}, {"tool": "b", "args": {}}, {"tool": "c", "args": {}}]

    def test_reorder_does_not_mutate_input(self):
        result = move_step(self.steps, 2, 0)
        self.assertEqual([s["tool"] for s in result], ["c", "a", "b"])
        self.assertEqual([s["tool"] for s in self.steps], ["a", "b", "c"])

    def test_replace_delete(self):
        s = replace_step(self.steps, 1, {"tool": "x", "args": {"name": "n"}})
        self.assertEqual(s[1]["tool"], "x")
        self.assertEqual(len(delete_step(s, 1)), 2)

    def test_invalid_indexes(self):
        with self.assertRaises(IndexError): move_step(self.steps, 99, 0)
        with self.assertRaises(IndexError): delete_step(self.steps, -1)


if __name__ == "__main__":
    unittest.main()
