import unittest
from garfield_agent.vision import analyze_screen, require_loopback


class FakeResponse:
    def raise_for_status(self): pass
    def json(self): return {"response": "Видно окно браузера"}


class FakeClient:
    def __init__(self): self.payload = None
    def post(self, url, json, timeout):
        self.payload = (url, json)
        return FakeResponse()


class VisionTests(unittest.TestCase):
    def test_local_only(self):
        for url in ("https://api.example.org/api/generate", "http://192.168.1.4/api/generate",
                    "file:///etc/passwd", "http://example.org", "http://user:pw@localhost:11434"):
            with self.assertRaises(ValueError):
                require_loopback(url)
        require_loopback("http://127.0.0.1:11434/api/generate")

    def test_vision_bytes_only_sent_to_loopback(self):
        fake = FakeClient()
        result = analyze_screen("Опиши экран", image_bytes=b"fake jpeg", session=fake)
        self.assertIn("окно браузера", result)
        self.assertEqual(fake.payload[0], "http://127.0.0.1:11434/api/generate")
        self.assertEqual(fake.payload[1]["model"], "llava:7b")
        self.assertEqual(len(fake.payload[1]["images"]), 1)

    def test_rejects_large_capture_before_network(self):
        with self.assertRaises(ValueError):
            analyze_screen("screen", image_bytes=b"x" * 3_500_001, session=FakeClient())


if __name__ == "__main__":
    unittest.main()
