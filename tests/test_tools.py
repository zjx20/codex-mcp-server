from __future__ import annotations

from http.client import HTTPConnection
import json
import os
import tempfile
from threading import Thread
import unittest
from pathlib import Path

from codex_mcp_server.server import McpServer, create_http_server
from codex_mcp_server.tools import CodexToolServer


class ToolServerTests(unittest.TestCase):
    def test_shell_exec_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = CodexToolServer(Path(tmp))
            try:
                result = server.call_tool(
                    "exec_command",
                    {
                        "cmd": "printf hello",
                        "workdir": tmp,
                        "yield_time_ms": 2000,
                        "login": False,
                    },
                )
                payload = json.loads(result["content"][0]["text"])
                self.assertEqual(payload["exit_code"], 0)
                self.assertEqual(payload["output"], "hello")
            finally:
                server.shutdown()

    def test_plan_and_goal_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            old_state = os.environ.get("CODEX_MCP_STATE")
            os.environ["CODEX_MCP_STATE"] = str(state_path)
            try:
                server = CodexToolServer(Path(tmp))
                server.call_tool(
                    "update_plan",
                    {"plan": [{"step": "inspect", "status": "in_progress"}]},
                )
                server.call_tool("create_goal", {"objective": "finish task", "token_budget": 10})
                goal = server.call_tool("get_goal", {})
                payload = json.loads(goal["content"][0]["text"])
                self.assertEqual(payload["objective"], "finish task")
                completed = server.call_tool("update_goal", {"status": "complete"})
                self.assertEqual(json.loads(completed["content"][0]["text"])["status"], "complete")
            finally:
                if old_state is None:
                    os.environ.pop("CODEX_MCP_STATE", None)
                else:
                    os.environ["CODEX_MCP_STATE"] = old_state

    def test_json_rpc_initialize_and_tools_list(self) -> None:
        server = McpServer()
        init = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )
        self.assertEqual(init["result"]["serverInfo"]["name"], "codex-mcp-server")
        self.assertIn("prompts", init["result"]["capabilities"])
        tools = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {tool["name"] for tool in tools["result"]["tools"]}
        self.assertEqual(
            names,
            {
                "exec_command",
                "shell_command",
                "write_stdin",
                "apply_patch",
                "update_plan",
                "get_goal",
                "create_goal",
                "update_goal",
                "tool_search",
                "multi_tool_use.parallel",
            },
        )
        server.tools.shutdown()

    def test_json_rpc_prompts_list_and_get(self) -> None:
        server = McpServer()
        prompts = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})
        self.assertEqual(prompts["result"]["prompts"][0]["name"], "codex-mcp-client")

        prompt = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "prompts/get",
                "params": {"name": "codex-mcp-client"},
            }
        )
        messages = prompt["result"]["messages"]
        self.assertEqual(messages[0]["role"], "user")
        self.assertIn(
            "Use this prompt as system or developer instructions",
            messages[0]["content"]["text"],
        )
        self.assertIn("Available Local Tools", messages[0]["content"]["text"])
        server.tools.shutdown()

    def test_json_rpc_prompts_get_unknown_prompt(self) -> None:
        server = McpServer()
        result = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "prompts/get",
                "params": {"name": "missing"},
            }
        )
        self.assertEqual(result["error"]["code"], -32602)
        server.tools.shutdown()

    def test_json_rpc_batch(self) -> None:
        server = McpServer()
        batch = server.handle_raw_message(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            ]
        )
        self.assertEqual(len(batch), 2)
        self.assertEqual(batch[0]["result"], {})
        self.assertIn("tools", batch[1]["result"])
        server.tools.shutdown()

    def test_http_post_json_rpc_request(self) -> None:
        httpd, thread, port = self._start_http_server()
        try:
            response, body = self._http_request(
                port,
                "POST",
                "/mcp",
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            )
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "application/json")
            self.assertEqual(json.loads(body), {"jsonrpc": "2.0", "id": 1, "result": {}})
        finally:
            self._stop_http_server(httpd, thread)

    def test_http_notification_returns_accepted(self) -> None:
        httpd, thread, port = self._start_http_server()
        try:
            response, body = self._http_request(
                port,
                "POST",
                "/mcp",
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            self.assertEqual(response.status, 202)
            self.assertEqual(body, "")
        finally:
            self._stop_http_server(httpd, thread)

    def test_http_get_without_sse_returns_method_not_allowed(self) -> None:
        httpd, thread, port = self._start_http_server()
        try:
            response, body = self._http_request(port, "GET", "/mcp")
            self.assertEqual(response.status, 405)
            self.assertEqual(response.getheader("Allow"), "POST")
            self.assertEqual(body, "")
        finally:
            self._stop_http_server(httpd, thread)

    def test_http_origin_validation_rejects_untrusted_origin(self) -> None:
        httpd, thread, port = self._start_http_server()
        try:
            response, body = self._http_request(
                port,
                "POST",
                "/mcp",
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"Origin": "http://evil.example"},
            )
            self.assertEqual(response.status, 403)
            self.assertEqual(json.loads(body)["error"]["message"], "Forbidden origin")
        finally:
            self._stop_http_server(httpd, thread)

    def _start_http_server(self):
        httpd = create_http_server("127.0.0.1", 0, "/mcp")
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd, thread, httpd.server_address[1]

    def _stop_http_server(self, httpd, thread) -> None:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()
        httpd.mcp_server.shutdown()

    def _http_request(
        self,
        port: int,
        method: str,
        path: str,
        payload=None,
        headers: dict[str, str] | None = None,
    ):
        body = None if payload is None else json.dumps(payload)
        request_headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            data = response.read().decode("utf-8")
            return response, data
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
