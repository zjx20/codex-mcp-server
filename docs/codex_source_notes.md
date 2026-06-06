# Codex Source Notes

Evidence source:

- Repository: `https://github.com/openai/codex.git`
- Local clone: `third_party/codex`
- Inspected commit: `87b808bb570f01f4b6fc8485c5459052fac0e320`
- Public manual cache: `/tmp/openai-docs-cache/codex-manual.md`

## Tool Planning

The official Rust implementation builds the model-visible tool set in
`third_party/codex/codex-rs/core/src/tools/spec_plan.rs`.

Important branches:

- Shell tools: `add_shell_tools`
- Core utility tools: `add_core_utility_tools`
- Collaboration/subagent tools: `add_collaboration_tools`
- MCP resource tools: `add_mcp_resource_tools`
- Runtime MCP passthrough tools: `add_mcp_runtime_tools`
- Extension tools: `add_extension_tools`
- Hosted web/image tools: `hosted_model_tool_specs`

## Tool Inventory

See `docs/tool_matrix.md` for the detailed tool-by-tool status table.

Implemented locally:

- `exec_command`: schema in `core/src/tools/handlers/shell_spec.rs`; execution flow in `handlers/unified_exec/exec_command.rs` and `core/src/unified_exec`.
- `write_stdin`: schema in `core/src/tools/handlers/shell_spec.rs`; execution flow in `handlers/unified_exec/write_stdin.rs`.
- `shell_command`: legacy schema in `core/src/tools/handlers/shell_spec.rs`; implemented here as a compatibility alias over `exec_command`.
- `apply_patch`: grammar in `core/src/tools/handlers/apply_patch.lark`; parser and filesystem algorithm in `codex-rs/apply-patch/src/parser.rs` and `codex-rs/apply-patch/src/lib.rs`.
- `update_plan`: schema in `core/src/tools/handlers/plan_spec.rs`; argument model in `protocol/src/plan_tool.rs`.
- `create_goal`, `get_goal`, `update_goal`: schema in `codex-rs/ext/goal/src/spec.rs`; lifecycle rules in `codex-rs/ext/goal`.
- `tool_search`: official deferred-tool search schema in `core/src/tools/handlers/tool_search_spec.rs`; implemented here as local metadata search.
- `multi_tool_use.parallel`: present in current Codex tool surface as a developer-tool wrapper; implemented here as concurrent nested tool calls.

The public MCP tool interface is exactly the tools returned by `tools/list`.

## Prompt Sources

The base Codex instructions live at:

- `third_party/codex/codex-rs/protocol/src/prompts/base_instructions/default.md`
- Extracted copy: `prompts/openai_codex_base_instructions.default.md`

Additional developer messages are assembled from context fragments:

- Permissions: `codex-rs/prompts/src/permissions_instructions.rs` and `codex-rs/prompts/templates/permissions`
- Environment context: `codex-rs/core/src/context/environment_context.rs`
- AGENTS.md guidance: base prompt plus `codex-rs/core/src/agents_md.rs`
- Goal continuation prompts: `codex-rs/prompts/templates/goals`
- Skills/apps/plugin instructions: `codex-rs/core/src/context/*instructions.rs`
- Apply patch usage guidance: `codex-rs/prompts/templates/apply_patch_tool_instructions.md`

`prompts/codex_mcp_client_system_prompt.md` adapts these sources for a generic
MCP client that uses this Python server rather than the Codex host. It focuses
on the tools returned by this server's `tools/list`.
