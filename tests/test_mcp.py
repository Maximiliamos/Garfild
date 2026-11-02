import json
import tempfile
import unittest
from pathlib import Path

from garfield_agent.mcp_client import LocalMCP


class Response:
    status_code = 200
    def __init__(self, result, headers=None):
        self.payload = result
        self.headers = headers or {"Content-Type": "application/json"}
    def raise_for_status(self): pass
    def json(self): return self.payload


class Session:
    def __init__(self): self.calls = []
    def post(self, endpoint, **kwargs):
        self.calls.append(kwargs["json"]["method"])
        method = kwargs["json"]["method"]
        if method == "initialize":
            return Response({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26"}}, {"Content-Type": "application/json", "Mcp-Session-Id": "xyz"})
        if method == "tools/list":
            return Response({"result": {"tools": [{"name": "read_test"}]}})
        if method == "tools/call":
            return Response({"result": {"content": [{"type": "text", "text": "ok"}]}})
        return Response({})


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "mcp.json"

    def config_server(self, url="http://127.0.0.1:9000/mcp"):
        self.config.write_text(json.dumps({"servers": {"test": {"url": url, "allowed_tools": ["read_test"]}}}))

    def test_server_must_be_loopback(self):
        self.config_server("http://192.168.1.42:9000/mcp")
        with self.assertRaises(ValueError):
            LocalMCP(self.config).servers()

    def test_tool_allowlist_and_explicit_call(self):
        self.config_server()
        mock = Session()
        mcp = LocalMCP(self.config, mock)
        with self.assertRaises(PermissionError):
            mcp.call("test", "run_shell", {})
        self.assertFalse(mock.calls)
        self.assertIn("ok", mcp.call("test", "read_test", {}))
        self.assertEqual(mock.calls, ["initialize", "notifications/initialized", "tools/list", "tools/call"])


if __name__ == "__main__":
    unittest.main()
