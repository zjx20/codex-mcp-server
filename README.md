# Codex MCP Server (Python)

This project is a Python MCP server that mirrors the locally executable Codex
CLI tool surface for use from other MCP-capable LLM clients. It supports both
stdio and Streamable HTTP transports.

It is intentionally not a wrapper around `codex mcp-server`. The implementation
recreates the local tool behavior that does not require an OpenAI model or Codex
host UI:

- `exec_command`, `write_stdin`, and legacy `shell_command`
- `apply_patch`
- `update_plan`
- `create_goal`, `get_goal`, `update_goal`
- `tool_search`
- `multi_tool_use.parallel`

The server only advertises tools that it implements locally.

## Run

From this repository:

```bash
PYTHONPATH=src python3 -m codex_mcp_server
```

For an MCP client config, use an absolute path:

```json
{
  "mcpServers": {
    "codex-tools": {
      "command": "python3",
      "args": ["-m", "codex_mcp_server"],
      "env": {
        "PYTHONPATH": "/workspaces/chatgpt-web-codex/src",
        "CODEX_MCP_CWD": "/path/to/your/project"
      }
    }
  }
}
```

`CODEX_MCP_CWD` controls the default working directory for shell commands,
relative patch paths, and `.codex_mcp_state.json`.

To run the same server over HTTP:

```bash
PYTHONPATH=src python3 -m codex_mcp_server --transport http --host 127.0.0.1 --port 8765 --path /mcp
```

HTTP clients that support MCP Streamable HTTP can point at:

```json
{
  "mcpServers": {
    "codex-tools-http": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

The HTTP transport returns JSON-RPC responses directly from POST requests. It
does not provide an SSE stream, so GET requests to `/mcp` return `405 Method
Not Allowed`.

HTTP security defaults are intentionally local-first:

- The default bind address is `127.0.0.1`.
- Incoming HTTP requests with an `Origin` header must come from localhost,
  `127.0.0.1`, `::1`, the configured bind host, or an explicit allowlist entry.
- Add extra browser origins with repeated `--allowed-origin` flags or the
  comma-separated `CODEX_MCP_ALLOWED_ORIGINS` environment variable.
- The server has no built-in authentication; do not bind it to a LAN/public
  interface unless you put it behind your own authentication and network
  controls.

## MCP Surface

During `initialize`, the server declares:

- `tools`: local Codex-style tool calls.
- `prompts`: a usage prompt for hosts/agents.

`prompts/list` exposes one prompt:

- `codex-mcp-client`: practical instructions for an LLM/agent using this server's
  tools. `prompts/get` returns the contents of
  `prompts/codex_mcp_client_system_prompt.md`.

`tools/list` exposes local shell, patch, plan, goal, metadata-search, and
parallel tool-call tools.

## Prompt

Use `prompts/codex_mcp_client_system_prompt.md`, or retrieve
`codex-mcp-client` through `prompts/get`, as the practical client-side system or
developer prompt for this server. The exact OpenAI Codex base prompt from the
inspected source is also extracted to
`prompts/openai_codex_base_instructions.default.md`.

## Source Evidence

The OpenAI Codex repository was cloned to `third_party/codex` at commit
`87b808bb570f01f4b6fc8485c5459052fac0e320`. See
`docs/codex_source_notes.md` for source notes, `docs/tool_matrix.md` for the
tool-by-tool implementation matrix, and `docs/prompt_assembly.md` for prompt
assembly details.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
