"""DPAPI round-trip on Windows; refuse plaintext persistence on other OSes."""
import os
import unittest

from garfield_agent import secrets


class SecretTests(unittest.TestCase):
    def test_empty_credentials(self):
        self.assertEqual(secrets.for_disk({"nvidia_api_key": ""})["nvidia_api_key"], "")
        self.assertEqual(secrets.from_disk({"nvidia_api_key": ""})["nvidia_api_key"], "")

    def test_encrypt_roundtrip_or_refuse_plaintext(self):
        raw = "TEST-LOCAL-CREDENTIAL-123"
        if os.name == "nt":
            stored = secrets.for_disk({"openai_api_key": raw})
            self.assertNotIn(raw, stored["openai_api_key"])
            self.assertTrue(stored["openai_api_key"].startswith(secrets.PREFIX))
            self.assertEqual(secrets.from_disk(stored)["openai_api_key"], raw)
        else:
            with self.assertRaises(RuntimeError):
                secrets.for_disk({"openai_api_key": raw})


if __name__ == "__main__":
    unittest.main()
