# Codex MCP Prompt

`prompts/codex_mcp_client_system_prompt.md` is for the model/agent inside an MCP
host that needs to use this Python server's tools well. It should be installed
as system or developer instructions when a model has access to
`codex-mcp-server`.

The server also exposes this prompt through MCP:

- `prompts/list` returns `codex-mcp-client`.
- `prompts/get` with `{"name": "codex-mcp-client"}` returns the prompt as a text
  message.

## Prompt Files

- Tool-use prompt for this MCP server:
  `prompts/codex_mcp_client_system_prompt.md`
- Exact Codex base prompt copied from source:
  `prompts/openai_codex_base_instructions.default.md`

`openai_codex_base_instructions.default.md` is the verbatim upstream source
prompt. The MCP client prompt is the project-specific adaptation: it preserves
the base prompt's guidance structure, but replaces Codex CLI-only assumptions
with this server's concrete MCP tool surface and host integration boundaries.

## Source Fragments

| Fragment | Source path | Purpose |
| --- | --- | --- |
| Base instructions | `codex-rs/protocol/src/prompts/base_instructions/default.md` | Agent identity, working style, AGENTS.md rules, planning, tool use, validation, final response style. |
| Apply patch instructions | `codex-rs/prompts/templates/apply_patch_tool_instructions.md` | Codex patch grammar and examples. |
| Permissions instructions | `codex-rs/prompts/src/permissions_instructions.rs`, `codex-rs/prompts/templates/permissions/*` | Sandbox and approval policy guidance. |
| Environment context | `codex-rs/core/src/context/environment_context.rs` | CWD, date/timezone, shell, filesystem permissions, workspace roots. |
| AGENTS.md context | `codex-rs/core/src/agents_md.rs` | Repo-scoped human instructions. |
| Goal prompts | `codex-rs/prompts/templates/goals/*` | Continuation, budget limit, and objective update steering for persistent goals. |
| Skills/apps/plugins | `codex-rs/core/src/context/*instructions.rs` | Available skills, plugins, apps, and image-generation guidance. |
| Review prompts | `codex-rs/prompts/templates/review/*` | Dedicated review-mode rubric and exit messages. |

## Adaptation Rules

| Source area | Status in this repo | Notes |
| --- | --- | --- |
| Static base prompt | Extracted verbatim | `prompts/openai_codex_base_instructions.default.md` mirrors `protocol/src/prompts/base_instructions/default.md` from the inspected commit. |
| Generic coding behavior | Adapted for this MCP server | Included in `prompts/codex_mcp_client_system_prompt.md` with the same broad guidance shape as the Codex base prompt, without Codex CLI-only assumptions. |
| Apply patch guidance | Adapted for MCP calls | The prompt tells the agent to call `apply_patch` with the patch body instead of invoking shell redirection or Codex CLI internals. |
| Environment context | Client-supplied | CWD, shell, date, filesystem permissions, and workspace roots depend on the host client. |
| AGENTS.md context | Client/resolver-supplied | The prompt instructs the model to inspect applicable repo instructions. |
| Persistent goals | Adapted | This server has local goal state tools, so completion and blocked semantics are included. |
| Review mode | Adapted | The prompt includes review stance and finding priorities at a practical level. |

## Host Integration

For another MCP-capable LLM client:

1. Prefer retrieving `codex-mcp-client` with `prompts/get`.
2. Add a small environment block with the client's actual workspace path,
   current date, shell, and security expectations.
3. Add any repo instructions from `AGENTS.md` or equivalent project files.
4. Let `tools/list` be the source of truth for callable tools.

The adapted prompt is intentionally agent-facing rather than explanatory. Its
reader is the model/agent using this MCP server, so the prompt combines general
Codex coding-agent guidance with concrete rules for the local tools exposed by
this server.
