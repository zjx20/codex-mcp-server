# MCP Client Configuration

Generic stdio configuration:

```json
{
  "mcpServers": {
    "codex-tools": {
      "command": "python3",
      "args": ["-m", "codex_mcp_server"],
      "env": {
        "PYTHONPATH": "/workspaces/chatgpt-web-codex/src",
        "CODEX_MCP_CWD": "/path/to/workspace"
      }
    }
  }
}
```

Generic Streamable HTTP configuration for clients that support URL-based MCP
servers:

```bash
PYTHONPATH=src python3 -m codex_mcp_server --transport http --host 127.0.0.1 --port 8765 --path /mcp
```

```json
{
  "mcpServers": {
    "codex-tools-http": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

The HTTP endpoint accepts JSON-RPC messages with POST and returns
`application/json` responses. Notifications and client JSON-RPC responses are
accepted with HTTP 202 and no response body. This server does not implement an
SSE stream, so GET and DELETE on `/mcp` return HTTP 405.

Hosts that support MCP prompts can discover `codex-mcp-client` through
`prompts/list` and retrieve it with `prompts/get`. Use that prompt as the
system or developer instruction for the model that will call this server's
tools.

Optional environment variables:

- `CODEX_MCP_CWD`: default workspace for shell commands, patches, and state.
- `CODEX_MCP_STATE`: explicit path for plan/goal state JSON.
- `CODEX_MCP_ALLOWED_ORIGINS`: comma-separated extra HTTP `Origin` values to
  allow, for example `http://localhost:3000,http://127.0.0.1:5173`.

Security note: this server executes local shell commands and edits files with
the permissions of the process that launches it. It does not implement Codex's
native sandbox or approval UI. Use it only for trusted workspaces or inside an
external sandbox.

For HTTP, keep the default `127.0.0.1` bind address unless you have external
authentication and network controls. The server validates incoming `Origin`
headers and rejects untrusted origins with HTTP 403, but it does not implement
user authentication.
