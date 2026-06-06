# Codex Tool Matrix

This matrix maps the Python MCP server's public tool surface to the inspected
Codex source areas it mirrors.

Source entry point: `third_party/codex/codex-rs/core/src/tools/spec_plan.rs`.

## Implemented Tools

| Tool | Python behavior | Codex source |
| --- | --- | --- |
| `exec_command` | Starts a local shell command, waits for bounded output, returns `exit_code` or `session_id`. Supports PTY with `tty=true`. | `core/src/tools/handlers/shell_spec.rs`, `handlers/unified_exec/exec_command.rs`, `core/src/unified_exec` |
| `write_stdin` | Sends text to a live `exec_command` session or polls it. | `core/src/tools/handlers/shell_spec.rs`, `handlers/unified_exec/write_stdin.rs` |
| `shell_command` | Legacy compatibility wrapper over `exec_command`. | `core/src/tools/handlers/shell_spec.rs`, `handlers/shell/shell_command.rs` |
| `apply_patch` | Parses Codex patch grammar, adds/deletes/updates/moves files with context matching. | `core/src/tools/handlers/apply_patch.lark`, `codex-rs/apply-patch/src/parser.rs`, `codex-rs/apply-patch/src/lib.rs` |
| `update_plan` | Persists the current plan in `.codex_mcp_state.json`; enforces one `in_progress` item. | `core/src/tools/handlers/plan_spec.rs`, `protocol/src/plan_tool.rs` |
| `create_goal` | Creates a persistent active goal when none exists. | `ext/goal/src/spec.rs`, `ext/goal/src/tool.rs` |
| `get_goal` | Reads persistent goal state plus elapsed time and remaining token budget when known. | `ext/goal/src/spec.rs`, `ext/goal/src/tool.rs` |
| `update_goal` | Marks the active goal `complete` or `blocked`. | `ext/goal/src/spec.rs`, `ext/goal/src/tool.rs` |
| `tool_search` | Searches this server's local tool metadata. | `core/src/tools/handlers/tool_search_spec.rs`, `core/src/tools/handlers/tool_search.rs` |
| `multi_tool_use.parallel` | Runs independent local tool calls through a thread pool and returns per-call results. | Current Codex developer tool surface; conceptually matches Codex's parallel tool wrapper behavior. |

## Implementation Notes

- Shell commands run with the permissions of the process that starts the MCP
  server. Codex's native sandbox is not recreated here.
- `apply_patch` follows Codex's lenient parser behavior for patch markers and
  heredoc wrapping, but it is implemented in Python rather than linking the
  Rust crate.
- Tool results follow MCP `CallToolResult` shape: `content`, optional
  `structuredContent`, and `isError` for tool-level failures.
- `tools/list` is the source of truth for the public tool interface.
