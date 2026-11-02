"""Minimal MCP Streamable HTTP client for explicitly allowlisted local tools.

Supports JSON responses and simple SSE data events. No stdio launch, no remote
servers, no implicit tool execution or credential delegation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit


from .vision import require_loopback

NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class LocalMCP:
    def __init__(self, config: Path, session=None):
        self.config = Path(config)
        # Do not import the HTTP dependency until a server is actually called.
        # Offline tests and local skills must work without requests installed.
        self.session = session

    def servers(self) -> dict[str, dict]:
        if not self.config.exists():
            return {}
        data = json.loads(self.config.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("servers"), dict):
            raise ValueError("MCP: требуются servers в JSON")
        parsed = {}
        for name, item in data["servers"].items():
            if not NAME.fullmatch(name) or not isinstance(item, dict):
                raise ValueError("MCP: неверное имя сервера")
            url = item.get("url", "")
            if not isinstance(url, str):
                raise ValueError("MCP: URL должен быть строкой")
            require_loopback(url)
            parsed_url = urlsplit(url)
            if parsed_url.path not in ("/mcp", "/mcp/") or parsed_url.query:
                raise ValueError("MCP: разрешены только localhost endpoints /mcp")
            allowed = item.get("allowed_tools")
            if not isinstance(allowed, list) or not allowed or any(
                not isinstance(t, str) or not NAME.fullmatch(t) for t in allowed
            ):
                raise ValueError("MCP: явно перечислите allowed_tools")
            parsed[name] = {"url": url, "allowed_tools": frozenset(allowed)}
        return parsed

    @staticmethod
    def _result(response):
        response.raise_for_status()
        if response.status_code == 202:
            return {}
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            events = [
                line[5:].strip() for line in response.text.splitlines()
                if line.startswith("data:") and line[5:].strip() and line[5:].strip() != "[DONE]"
            ]
            if not events:
                raise RuntimeError("MCP SSE не содержал результата")
            return json.loads(events[-1])
        return response.json()

    def _post(self, endpoint: str, payload: dict, session_id: str | None = None):
        if self.session is None:
            import requests
            self.session = requests.Session()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        response = self.session.post(endpoint, headers=headers, json=payload, timeout=(3, 20), allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            raise RuntimeError("MCP redirects are not allowed")
        return response, self._result(response)

    def call(self, server: str, tool: str, arguments: dict) -> str:
        servers = self.servers()
        if server not in servers or tool not in servers[server]["allowed_tools"]:
            raise PermissionError("MCP-сервер или инструмент не разрешён конфигурацией")
        if not isinstance(arguments, dict) or len(json.dumps(arguments)) > 3000:
            raise ValueError("MCP arguments должны быть небольшим JSON-объектом")
        endpoint = servers[server]["url"]
        init, result = self._post(endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "Garfield", "version": "0.4"},
            },
        })
        if not isinstance(result, dict) or ("error" in result):
            raise RuntimeError("MCP initialize failed")
        session_id = init.headers.get("Mcp-Session-Id")
        # Session notification is required by stateful Streamable HTTP servers.
        self._post(endpoint, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)
        _, tools_result = self._post(endpoint, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }, session_id)
        listed = tools_result.get("result", {}).get("tools", [])
        if not isinstance(listed, list) or tool not in {x.get("name") for x in listed if isinstance(x, dict)}:
            raise PermissionError("Инструмент отсутствует в объявленном MCP-каталоге сервера")
        _, reply = self._post(endpoint, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }, session_id)
        if not isinstance(reply, dict) or reply.get("error"):
            raise RuntimeError("Ошибка MCP tools/call: " + str(reply.get("error"))[:300])
        result = reply.get("result", {})
        if result.get("isError"):
            raise RuntimeError("MCP-инструмент сообщил ошибку")
        return json.dumps(result.get("content", result), ensure_ascii=False)[:4500]
