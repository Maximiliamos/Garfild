"""Constrained MCP Streamable HTTP client (protocol 2025-03-26).

Only explicitly configured loopback servers and allowlisted tools. Each request
is a separate POST. Supports JSON and bounded SSE responses, 202 notifications,
session IDs and paginated tools/list. It does not grant the server autonomous
access or implement server-initiated sampling/elicitation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from .vision import require_loopback


NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PROTOCOL = "2025-03-26"
MAX_RESPONSE_BYTES = 512_000
MAX_TOOL_PAGES = 8


class LocalMCP:
    def __init__(self, config: Path, session=None):
        self.config = Path(config)
        self.session = session

    def servers(self) -> dict[str, dict]:
        if not self.config.exists():
            return {}
        if self.config.stat().st_size > 64_000:
            raise ValueError("MCP: файл конфигурации слишком большой")
        data = json.loads(self.config.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("servers"), dict):
            raise ValueError("MCP: требуются servers в JSON")
        parsed = {}
        for name, item in data["servers"].items():
            if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(item, dict):
                raise ValueError("MCP: неверное имя сервера")
            url = item.get("url", "")
            if not isinstance(url, str):
                raise ValueError("MCP: URL должен быть строкой")
            require_loopback(url)
            address = urlsplit(url)
            if address.path not in ("/mcp", "/mcp/") or address.query:
                raise ValueError("MCP: разрешены только localhost endpoints /mcp")
            try:
                port = address.port
            except ValueError as exc:
                raise ValueError("MCP: неверный порт") from exc
            if port is None:
                raise ValueError("MCP: укажите явный порт локального сервера")
            allowed = item.get("allowed_tools")
            if not isinstance(allowed, list) or not allowed or any(
                not isinstance(t, str) or not NAME.fullmatch(t) for t in allowed
            ):
                raise ValueError("MCP: явно перечислите allowed_tools")
            parsed[name] = {"url": url, "allowed_tools": frozenset(allowed)}
        return parsed

    @staticmethod
    def _sse_messages(text: str):
        """Decode SSE event boundaries, preserving multi-line data fields."""
        data = []
        for line in (text + "\n\n").splitlines():
            if not line:
                if data:
                    value = "\n".join(data)
                    data.clear()
                    if value != "[DONE]":
                        yield json.loads(value)
                continue
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            # Ignore event, id, retry and comment lines.

    @classmethod
    def _result(cls, response, expected_id: int | None):
        response.raise_for_status()
        if response.status_code == 202:
            if expected_id is not None:
                raise RuntimeError("MCP: сервер вернул 202 вместо ответа на запрос")
            return {}
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if mime == "text/event-stream":
            text = response.text
            if len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ValueError("MCP: SSE ответ превышает лимит")
            candidates = cls._sse_messages(text)
        elif mime == "application/json" or mime.endswith("+json"):
            if len(getattr(response, "content", b"")) > MAX_RESPONSE_BYTES:
                raise ValueError("MCP: JSON ответ превышает лимит")
            candidates = iter([response.json()])
        else:
            raise RuntimeError("MCP: неподдерживаемый Content-Type: " + mime[:100])
        for obj in candidates:
            if not isinstance(obj, dict) or obj.get("jsonrpc") != "2.0":
                raise RuntimeError("MCP: неверный JSON-RPC ответ")
            if expected_id is None:
                # Notifications should return 202; tolerate a JSON-RPC
                # notification without interpreting it as a request result.
                if "id" not in obj:
                    continue
                raise RuntimeError("MCP: неожиданный ответ на уведомление")
            if obj.get("id") == expected_id:
                if "error" in obj:
                    raise RuntimeError("MCP: " + str(obj["error"])[:300])
                if "result" not in obj:
                    raise RuntimeError("MCP: отсутствует result")
                return obj
            # Progress notifications and unrelated responses cannot be
            # mistaken for the result of our requested tool.
        raise RuntimeError("MCP: не получен ответ с нужным JSON-RPC id")

    def _post(self, endpoint: str, payload: dict, session_id: str | None = None):
        if self.session is None:
            import requests
            self.session = requests.Session()
            self.session.trust_env = False  # Don't proxy localhost via HTTP(S)_PROXY.
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if session_id:
            if not isinstance(session_id, str) or len(session_id) > 160 or not session_id.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in session_id):
                raise ValueError("MCP: некорректный session-id")
            headers["Mcp-Session-Id"] = session_id
        require_loopback(endpoint)
        response = self.session.post(
            endpoint, headers=headers, json=payload, timeout=(3, 20), allow_redirects=False
        )
        if 300 <= response.status_code < 400:
            raise RuntimeError("MCP: перенаправления запрещены")
        expected_id = payload.get("id")
        return response, self._result(response, expected_id)

    def call(self, server: str, tool: str, arguments: dict) -> str:
        servers = self.servers()
        if server not in servers or tool not in servers[server]["allowed_tools"]:
            raise PermissionError("MCP-сервер или инструмент не разрешён конфигурацией")
        if not isinstance(arguments, dict) or len(json.dumps(arguments, ensure_ascii=False)) > 3000:
            raise ValueError("MCP arguments должны быть небольшим JSON-объектом")
        endpoint = servers[server]["url"]
        init, reply = self._post(endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "Garfield", "version": "0.5"},
            },
        })
        details = reply.get("result")
        if not isinstance(details, dict) or details.get("protocolVersion") != PROTOCOL:
            raise RuntimeError("MCP: сервер не согласовал поддерживаемую версию протокола")
        session_id = init.headers.get("Mcp-Session-Id")
        self._post(endpoint, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)

        # Some servers paginate the tool catalogue. Never execute an
        # allowlisted name unless it was explicitly advertised.
        names = set()
        cursor = None
        seen_cursors = set()
        for page in range(MAX_TOOL_PAGES):
            params = {"cursor": cursor} if cursor else {}
            _, listed_response = self._post(endpoint, {
                "jsonrpc": "2.0", "id": 2 + page, "method": "tools/list", "params": params,
            }, session_id)
            result = listed_response.get("result", {})
            tools = result.get("tools") if isinstance(result, dict) else None
            if not isinstance(tools, list):
                raise RuntimeError("MCP: неверный каталог tools/list")
            names.update(x.get("name") for x in tools if isinstance(x, dict) and isinstance(x.get("name"), str))
            cursor = result.get("nextCursor")
            if not cursor:
                break
            if not isinstance(cursor, str) or len(cursor) > 250 or cursor in seen_cursors:
                raise RuntimeError("MCP: некорректный курсор каталога")
            seen_cursors.add(cursor)
        else:
            raise RuntimeError("MCP: каталог инструментов содержит слишком много страниц")
        if tool not in names:
            raise PermissionError("Инструмент отсутствует в объявленном MCP-каталоге сервера")
        _, call_reply = self._post(endpoint, {
            "jsonrpc": "2.0", "id": 20, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }, session_id)
        result = call_reply.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("MCP: пустой результат tools/call")
        if result.get("isError"):
            raise RuntimeError("MCP-инструмент сообщил ошибку")
        return json.dumps(result.get("content", result), ensure_ascii=False)[:4500]
