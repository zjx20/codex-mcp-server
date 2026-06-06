from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

from . import __version__
from .tools import CodexToolServer, ToolError


JSONRPC_VERSION = "2.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
HTTP_FALLBACK_PROTOCOL_VERSION = "2025-03-26"
SUPPORTED_HTTP_PROTOCOL_VERSIONS = {
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
}
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765
DEFAULT_HTTP_PATH = "/mcp"
LOCAL_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "::1"}
CLIENT_PROMPT_NAME = "codex-mcp-client"
CLIENT_PROMPT_TITLE = "Use Codex MCP Server"
CLIENT_PROMPT_DESCRIPTION = (
    "Instructions for an MCP host or agent using the Codex-style local tools exposed by this server."
)


class McpServer:
    def __init__(self) -> None:
        self.tools = CodexToolServer()
        self._lock = RLock()

    def serve_stdio(self) -> None:
        try:
            for line in sys.stdin:
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                    response = self.handle_raw_message_threadsafe(message)
                except Exception as exc:  # noqa: BLE001 - JSON-RPC server must not crash.
                    response = error_response(None, -32603, f"Internal error: {exc}")
                    print(traceback.format_exc(), file=sys.stderr)
                if response is not None:
                    send(response)
        finally:
            self.shutdown()

    def handle_raw_message_threadsafe(
        self, message: Any
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        with self._lock:
            return self.handle_raw_message(message)

    def handle_raw_message(self, message: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        if isinstance(message, list):
            responses = [self.handle_message(item) for item in message if isinstance(item, dict)]
            responses = [response for response in responses if response is not None]
            return responses or None
        if not isinstance(message, dict):
            return error_response(None, -32600, "Invalid JSON-RPC message")
        return self.handle_message(message)

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        if method == "notifications/initialized":
            return None
        if method == "initialize":
            protocol = params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION
            return result_response(
                request_id,
                {
                    "protocolVersion": protocol,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "codex-mcp-server",
                        "version": __version__,
                    },
                    "instructions": (
                        "Local Codex-style tools for shell execution, apply_patch edits, plan/goal state, "
                        f"and local tool metadata search. Retrieve prompt '{CLIENT_PROMPT_NAME}' with "
                        "prompts/get for practical host/agent instructions."
                    ),
                },
            )
        if method == "ping":
            return result_response(request_id, {})
        if method == "prompts/list":
            return result_response(request_id, {"prompts": list_prompts()})
        if method == "prompts/get":
            name = params.get("name")
            if name != CLIENT_PROMPT_NAME:
                return error_response(request_id, -32602, f"Unknown prompt: {name}")
            return result_response(request_id, get_client_prompt())
        if method == "tools/list":
            return result_response(request_id, {"tools": self.tools.list_tools()})
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str):
                return error_response(request_id, -32602, "tools/call requires params.name")
            try:
                result = self.tools.call_tool(name, params.get("arguments") or {})
            except (ToolError, ValueError, OSError) as exc:
                return result_response(
                    request_id,
                    {"content": [{"type": "text", "text": str(exc)}], "isError": True},
                )
            return result_response(request_id, result)
        return error_response(request_id, -32601, f"Method not found: {method}")

    def shutdown(self) -> None:
        self.tools.shutdown()


class CodexHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        mcp_server: McpServer,
        mcp_path: str,
        allowed_origins: set[str] | None = None,
    ) -> None:
        super().__init__(server_address, CodexHttpRequestHandler)
        self.mcp_server = mcp_server
        self.mcp_path = normalize_path(mcp_path)
        self.allowed_origins = allowed_origins or set()
        self.allowed_origin_hosts = allowed_origin_hosts(server_address[0])


class CodexHttpRequestHandler(BaseHTTPRequestHandler):
    server: CodexHttpServer

    def do_POST(self) -> None:
        if not self._is_mcp_path():
            self._send_status(404)
            return
        if not self._origin_is_allowed():
            self._send_json(403, error_response(None, -32000, "Forbidden origin"))
            return
        protocol_error = self._protocol_version_error()
        if protocol_error is not None:
            self._send_json(400, protocol_error)
            return

        try:
            message = self._read_json_body()
        except ValueError as exc:
            self._send_json(400, error_response(None, -32700, str(exc)))
            return

        if is_json_rpc_response(message):
            self._send_status(202)
            return

        try:
            response = self.server.mcp_server.handle_raw_message_threadsafe(message)
        except Exception as exc:  # noqa: BLE001 - JSON-RPC server must not crash.
            print(traceback.format_exc(), file=sys.stderr)
            response = error_response(None, -32603, f"Internal error: {exc}")

        if response is None:
            self._send_status(202)
            return
        self._send_json(200, response)

    def do_GET(self) -> None:
        if not self._is_mcp_path():
            self._send_status(404)
            return
        if not self._origin_is_allowed():
            self._send_json(403, error_response(None, -32000, "Forbidden origin"))
            return
        self._send_status(405, allow="POST")

    def do_DELETE(self) -> None:
        if not self._is_mcp_path():
            self._send_status(404)
            return
        if not self._origin_is_allowed():
            self._send_json(403, error_response(None, -32000, "Forbidden origin"))
            return
        self._send_status(405, allow="POST")

    def do_OPTIONS(self) -> None:
        if not self._is_mcp_path():
            self._send_status(404)
            return
        if not self._origin_is_allowed():
            self._send_json(403, error_response(None, -32000, "Forbidden origin"))
            return
        self._send_status(204, allow="POST")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _is_mcp_path(self) -> bool:
        return urlsplit(self.path).path == self.server.mcp_path

    def _origin_is_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin_is_allowed(origin, self.server.allowed_origin_hosts, self.server.allowed_origins)

    def _protocol_version_error(self) -> dict[str, Any] | None:
        protocol = self.headers.get("MCP-Protocol-Version") or HTTP_FALLBACK_PROTOCOL_VERSION
        if protocol not in SUPPORTED_HTTP_PROTOCOL_VERSIONS:
            return error_response(None, -32000, f"Unsupported MCP-Protocol-Version: {protocol}")
        return None

    def _read_json_body(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Missing request body")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        raw_body = self.rfile.read(length)
        try:
            text = raw_body.decode("utf-8")
            return json.loads(text)
        except UnicodeDecodeError as exc:
            raise ValueError("Request body must be UTF-8 JSON") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Parse error: {exc.msg}") from exc

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_status(self, status: int, allow: str | None = None) -> None:
        self.send_response(status)
        if allow is not None:
            self.send_header("Allow", allow)
        self.send_header("Content-Length", "0")
        self.end_headers()


def create_http_server(
    host: str = DEFAULT_HTTP_HOST,
    port: int = DEFAULT_HTTP_PORT,
    path: str = DEFAULT_HTTP_PATH,
    allowed_origins: set[str] | None = None,
    mcp_server: McpServer | None = None,
) -> CodexHttpServer:
    return CodexHttpServer(
        (host, port),
        mcp_server or McpServer(),
        path,
        allowed_origins_from_env() | (allowed_origins or set()),
    )


def serve_http(host: str, port: int, path: str, allowed_origins: set[str] | None = None) -> None:
    httpd = create_http_server(host, port, path, allowed_origins)
    try:
        address_host, address_port = httpd.server_address[:2]
        print(
            f"codex-mcp-server HTTP listening on http://{address_host}:{address_port}{httpd.mcp_path}",
            file=sys.stderr,
        )
        httpd.serve_forever()
    finally:
        httpd.server_close()
        httpd.mcp_server.shutdown()


def normalize_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def allowed_origins_from_env() -> set[str]:
    raw = os.environ.get("CODEX_MCP_ALLOWED_ORIGINS", "")
    return {normalize_origin(item.strip()) for item in raw.split(",") if item.strip()}


def allowed_origin_hosts(host: str) -> set[str]:
    hosts = set(LOCAL_ORIGIN_HOSTS)
    if host and host not in {"0.0.0.0", "::"}:
        hosts.add(host)
    return hosts


def normalize_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if not parsed.scheme or not parsed.netloc:
        return origin.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def origin_is_allowed(origin: str, allowed_hosts: set[str], allowed_origins: set[str]) -> bool:
    normalized = normalize_origin(origin)
    if normalized in allowed_origins:
        return True
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = parsed.hostname
    return hostname in allowed_hosts if hostname is not None else False


def is_json_rpc_response(message: Any) -> bool:
    if isinstance(message, dict):
        return "method" not in message and ("result" in message or "error" in message)
    if isinstance(message, list):
        return bool(message) and all(is_json_rpc_response(item) for item in message)
    return False


def list_prompts() -> list[dict[str, Any]]:
    return [
        {
            "name": CLIENT_PROMPT_NAME,
            "title": CLIENT_PROMPT_TITLE,
            "description": CLIENT_PROMPT_DESCRIPTION,
        }
    ]


def get_client_prompt() -> dict[str, Any]:
    return {
        "description": CLIENT_PROMPT_DESCRIPTION,
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": load_client_prompt_text(),
                },
            }
        ],
    }


def load_client_prompt_text() -> str:
    prompt_path = (
        Path(__file__).resolve().parents[2] / "prompts" / "codex_mcp_client_system_prompt.md"
    )
    return prompt_path.read_text(encoding="utf-8")


def result_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name,
        description="Run the Codex MCP server over stdio or Streamable HTTP.",
    )
    parser.add_argument(
        "--transport",
        choices={"stdio", "http"},
        default="stdio",
        help="Transport to serve. Defaults to stdio.",
    )
    parser.add_argument("--host", default=DEFAULT_HTTP_HOST, help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT, help="HTTP bind port.")
    parser.add_argument("--path", default=DEFAULT_HTTP_PATH, help="HTTP MCP endpoint path.")
    parser.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        help="Extra exact Origin value allowed for HTTP requests. May be repeated.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.transport == "http":
        serve_http(
            args.host,
            args.port,
            args.path,
            {normalize_origin(item) for item in args.allowed_origin},
        )
        return
    McpServer().serve_stdio()


if __name__ == "__main__":
    main()
