"""Protocol-level tests for local MCP without a network or HTTP dependency."""
import json
import tempfile
import unittest
from pathlib import Path

from garfield_agent.mcp_client import LocalMCP


class Response:
    def __init__(self, payload=None, *, status_code=200, headers=None, text=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")
        self.content = self.text.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


def reply(identifier, result):
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


class Session:
    def __init__(self, *, sse=False, paginated=False, bad_id=False, version="2025-03-26"):
        self.calls = []
        self.sse = sse
        self.paginated = paginated
        self.bad_id = bad_id
        self.version = version

    def post(self, endpoint, **kwargs):
        request = kwargs["json"]
        method = request["method"]
        self.calls.append((method, request.get("params", {}), kwargs))
        assert kwargs["allow_redirects"] is False
        assert endpoint == "http://127.0.0.1:9000/mcp"
        if method == "initialize":
            return Response(reply(1, {"protocolVersion": self.version}), headers={
                "Content-Type": "application/json", "Mcp-Session-Id": "test-session"
            })
        assert kwargs["headers"]["Mcp-Session-Id"] == "test-session"
        if method == "notifications/initialized":
            return Response(status_code=202)
        if method == "tools/list":
            index = request["id"]
            if self.paginated and index == 2:
                return Response(reply(2, {"tools": [{"name": "different"}], "nextCursor": "page2"}))
            return Response(reply(index, {"tools": [{"name": "read_test"}]}))
        if method == "tools/call":
            obj = reply(123 if self.bad_id else 20, {"content": [{"type": "text", "text": "ok"}]})
            if self.sse:
                notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}})
                body = (
                    ": keepalive\n\n"
                    "event: message\n"
                    f"data: {notification}\n\n"
                    "event: message\n"
                    "data: " + json.dumps(obj) + "\n\n"
                    f"data: {notification}\n\n"
                )
                return Response(headers={"Content-Type": "text/event-stream"}, text=body)
            return Response(obj)
        raise AssertionError(method)


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "mcp.json"

    def config_server(self, url="http://127.0.0.1:9000/mcp"):
        self.config.write_text(json.dumps({
            "servers": {"test": {"url": url, "allowed_tools": ["read_test"]}}
        }), encoding="utf-8")

    def test_server_must_be_loopback_and_explicit_port(self):
        for url in ("http://192.168.1.42:9000/mcp", "http://127.0.0.1/mcp",
                    "http://127.0.0.1:9000/admin", "http://127.0.0.1:9000/mcp?secret=x"):
            self.config_server(url)
            with self.assertRaises(ValueError):
                LocalMCP(self.config).servers()

    def test_tool_allowlist_and_explicit_call(self):
        self.config_server()
        session = Session()
        mcp = LocalMCP(self.config, session)
        with self.assertRaises(PermissionError):
            mcp.call("test", "run_shell", {})
        self.assertFalse(session.calls)
        self.assertIn("ok", mcp.call("test", "read_test", {}))
        self.assertEqual([x[0] for x in session.calls],
                         ["initialize", "notifications/initialized", "tools/list", "tools/call"])

    def test_sse_matches_jsonrpc_id_not_last_event(self):
        self.config_server()
        self.assertIn("ok", LocalMCP(self.config, Session(sse=True)).call("test", "read_test", {}))

    def test_unrelated_response_id_rejected(self):
        self.config_server()
        with self.assertRaisesRegex(RuntimeError, "id"):
            LocalMCP(self.config, Session(sse=True, bad_id=True)).call("test", "read_test", {})

    def test_catalogue_pagination(self):
        self.config_server()
        session = Session(paginated=True)
        self.assertIn("ok", LocalMCP(self.config, session).call("test", "read_test", {}))
        self.assertEqual(len([x for x in session.calls if x[0] == "tools/list"]), 2)

    def test_unsupported_protocol_rejected_before_tools(self):
        self.config_server()
        session = Session(version="2099-01-01")
        with self.assertRaisesRegex(RuntimeError, "версию протокола"):
            LocalMCP(self.config, session).call("test", "read_test", {})
        self.assertNotIn("tools/call", [x[0] for x in session.calls])

    def test_notification_accepted_and_request_202_rejected(self):
        accepted = Response(status_code=202)
        self.assertEqual(LocalMCP._result(accepted, None), {})
        with self.assertRaisesRegex(RuntimeError, "202"):
            LocalMCP._result(accepted, 2)

    def test_response_must_have_expected_jsonrpc_id(self):
        with self.assertRaisesRegex(RuntimeError, "id"):
            LocalMCP._result(Response(reply(555, {})), 2)
        with self.assertRaisesRegex(RuntimeError, "неверный JSON-RPC"):
            LocalMCP._result(Response({"id": 2, "result": {}}), 2)


if __name__ == "__main__":
    unittest.main()
