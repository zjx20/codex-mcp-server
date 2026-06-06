from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .patch import apply_patch_text
from .shell import ShellManager
from .state import StateStore


class ToolError(Exception):
    pass


JsonDict = dict[str, Any]
ToolHandler = Callable[[JsonDict], JsonDict]


class CodexToolServer:
    def __init__(self, cwd: Path | None = None) -> None:
        root = cwd or Path(os.environ.get("CODEX_MCP_CWD", os.getcwd()))
        self.cwd = root.expanduser().resolve()
        self.shell = ShellManager(self.cwd)
        self.state = StateStore(self.cwd)
        self.handlers: dict[str, ToolHandler] = {
            "exec_command": self.exec_command,
            "shell_command": self.shell_command,
            "write_stdin": self.write_stdin,
            "apply_patch": self.apply_patch,
            "update_plan": self.update_plan,
            "get_goal": self.get_goal,
            "create_goal": self.create_goal,
            "update_goal": self.update_goal,
            "tool_search": self.tool_search,
            "multi_tool_use.parallel": self.parallel,
        }

    def list_tools(self) -> list[JsonDict]:
        return TOOL_DEFINITIONS

    def call_tool(self, name: str, arguments: Any) -> JsonDict:
        if name not in self.handlers:
            raise ToolError(f"Unknown tool: {name}")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            if name == "apply_patch" and isinstance(arguments, str):
                arguments = {"patch": arguments}
            else:
                raise ToolError("Tool arguments must be a JSON object.")
        return self.handlers[name](arguments)

    def exec_command(self, args: JsonDict) -> JsonDict:
        return text_result(self.shell.exec_command(args))

    def shell_command(self, args: JsonDict) -> JsonDict:
        command = args.get("command")
        if not isinstance(command, str) or not command:
            raise ToolError("shell_command requires a non-empty command string.")
        mapped = {
            "cmd": command,
            "workdir": args.get("workdir"),
            "yield_time_ms": args.get("timeout_ms", 10000),
            "max_output_tokens": args.get("max_output_tokens", 10000),
            "login": args.get("login", True),
        }
        return text_result(self.shell.exec_command(mapped))

    def write_stdin(self, args: JsonDict) -> JsonDict:
        return text_result(self.shell.write_stdin(args))

    def apply_patch(self, args: JsonDict) -> JsonDict:
        patch = args.get("patch") or args.get("input")
        if not isinstance(patch, str) or not patch.strip():
            raise ToolError("apply_patch requires a non-empty 'patch' string argument.")
        workdir = Path(args.get("workdir") or self.cwd).expanduser()
        if not workdir.is_absolute():
            workdir = self.cwd / workdir
        result = apply_patch_text(patch, workdir.resolve())
        return text_result(result)

    def update_plan(self, args: JsonDict) -> JsonDict:
        plan = args.get("plan")
        if not isinstance(plan, list):
            raise ToolError("update_plan requires a 'plan' array.")
        normalized: list[dict[str, str]] = []
        for item in plan:
            if not isinstance(item, dict):
                raise ToolError("Each plan item must be an object.")
            step = item.get("step")
            status = item.get("status")
            if not isinstance(step, str) or not step.strip():
                raise ToolError("Each plan item requires a non-empty step string.")
            if status not in {"pending", "in_progress", "completed"}:
                raise ToolError("Plan item status must be pending, in_progress, or completed.")
            normalized.append({"step": step, "status": status})
        explanation = args.get("explanation")
        if explanation is not None and not isinstance(explanation, str):
            raise ToolError("explanation must be a string when provided.")
        return text_result(self.state.update_plan(normalized, explanation))

    def get_goal(self, args: JsonDict) -> JsonDict:
        return text_result(self.state.get_goal())

    def create_goal(self, args: JsonDict) -> JsonDict:
        objective = args.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            raise ToolError("create_goal requires a non-empty objective string.")
        token_budget = args.get("token_budget")
        if token_budget is not None:
            if not isinstance(token_budget, int):
                raise ToolError("token_budget must be an integer when provided.")
        return text_result(self.state.create_goal(objective, token_budget))

    def update_goal(self, args: JsonDict) -> JsonDict:
        status = args.get("status")
        if not isinstance(status, str):
            raise ToolError("update_goal requires a status string.")
        return text_result(self.state.update_goal(status))

    def tool_search(self, args: JsonDict) -> JsonDict:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError("tool_search requires a query string.")
        limit = int(args.get("limit") or 8)
        terms = [term.lower() for term in query.split() if term.strip()]
        matches: list[tuple[int, JsonDict]] = []
        for tool in TOOL_DEFINITIONS:
            haystack = f"{tool['name']} {tool.get('description', '')}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                matches.append((score, tool))
        matches.sort(key=lambda item: (-item[0], item[1]["name"]))
        return text_result({"tools": [tool for _, tool in matches[:limit]]})

    def parallel(self, args: JsonDict) -> JsonDict:
        tool_uses = args.get("tool_uses")
        if not isinstance(tool_uses, list):
            raise ToolError("multi_tool_use.parallel requires a tool_uses array.")
        results: list[JsonDict | None] = [None] * len(tool_uses)
        with ThreadPoolExecutor(max_workers=min(len(tool_uses), 8) or 1) as executor:
            futures = {}
            for index, use in enumerate(tool_uses):
                if not isinstance(use, dict):
                    raise ToolError("Each tool use must be an object.")
                recipient = use.get("recipient_name")
                parameters = use.get("parameters") or {}
                if not isinstance(recipient, str):
                    raise ToolError("Each tool use requires recipient_name.")
                tool_name = normalize_recipient_name(recipient, self.handlers)
                if tool_name == "multi_tool_use.parallel":
                    raise ToolError("parallel cannot recursively call itself.")
                futures[executor.submit(self.call_tool, tool_name, parameters)] = (index, tool_name)
            for future in as_completed(futures):
                index, tool_name = futures[future]
                try:
                    results[index] = {"tool": tool_name, "ok": True, "result": future.result()}
                except Exception as exc:  # noqa: BLE001 - surface per-tool failures to the model.
                    results[index] = {"tool": tool_name, "ok": False, "error": str(exc)}
        return text_result({"results": results})

    def shutdown(self) -> None:
        self.shell.shutdown()


def normalize_recipient_name(name: str, handlers: dict[str, ToolHandler]) -> str:
    if name in handlers:
        return name
    if "." in name:
        suffix = name.rsplit(".", 1)[-1]
        if suffix in handlers:
            return suffix
    raise ToolError(f"Unknown nested tool: {name}")


def text_result(value: Any) -> JsonDict:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    result: JsonDict = {"content": [{"type": "text", "text": text}]}
    if isinstance(value, dict):
        result["structuredContent"] = value
    return result


def schema(properties: JsonDict, required: list[str] | None = None) -> JsonDict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def string(description: str) -> JsonDict:
    return {"type": "string", "description": description}


def number(description: str) -> JsonDict:
    return {"type": "number", "description": description}


def boolean(description: str) -> JsonDict:
    return {"type": "boolean", "description": description}


def array(items: JsonDict, description: str) -> JsonDict:
    return {"type": "array", "items": items, "description": description}


TOOL_DEFINITIONS: list[JsonDict] = [
    {
        "name": "exec_command",
        "description": "Runs a command in a PTY or pipe, returning output or a session ID for ongoing interaction.",
        "inputSchema": schema(
            {
                "cmd": string("Shell command to execute."),
                "workdir": string("Working directory for the command. Defaults to the server cwd."),
                "tty": boolean("True allocates a PTY; false or omitted uses plain pipes."),
                "yield_time_ms": number("Wait before yielding output. Defaults to 10000 ms; effective range is 250-30000 ms."),
                "max_output_tokens": number("Output token budget. Defaults to 10000 approximate tokens."),
                "shell": string("Shell binary to launch. Defaults to the user's default shell."),
                "login": boolean("True runs the shell with login semantics; false disables them. Defaults to true."),
            },
            ["cmd"],
        ),
    },
    {
        "name": "shell_command",
        "description": "Legacy Codex shell tool. Runs a shell command and returns its output; prefer exec_command for interactive sessions.",
        "inputSchema": schema(
            {
                "command": string("Shell script to run in the user's default shell."),
                "workdir": string("Working directory for the command. Defaults to the server cwd."),
                "timeout_ms": number("Maximum initial wait. Defaults to 10000 ms."),
                "login": boolean("True runs with login shell semantics; false disables them. Defaults to true."),
                "max_output_tokens": number("Output token budget. Defaults to 10000 approximate tokens."),
            },
            ["command"],
        ),
    },
    {
        "name": "write_stdin",
        "description": "Writes characters to an existing exec_command session and returns recent output.",
        "inputSchema": schema(
            {
                "session_id": number("Identifier of the running exec session."),
                "chars": string("Bytes to write to stdin. Defaults to empty, which polls without writing."),
                "yield_time_ms": number("Wait before yielding output."),
                "max_output_tokens": number("Output token budget. Defaults to 10000 approximate tokens."),
            },
            ["session_id"],
        ),
    },
    {
        "name": "apply_patch",
        "description": "Apply a Codex apply_patch patch to files. Pass the freeform patch body as the 'patch' string.",
        "inputSchema": schema(
            {
                "patch": string("Patch text starting with *** Begin Patch and ending with *** End Patch."),
                "workdir": string("Working directory used to resolve relative patch paths. Defaults to the server cwd."),
            },
            ["patch"],
        ),
    },
    {
        "name": "update_plan",
        "description": "Updates the task plan. At most one step can be in_progress at a time.",
        "inputSchema": schema(
            {
                "explanation": string("Optional explanation for this plan update."),
                "plan": array(
                    schema(
                        {
                            "step": string("Task step text."),
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        },
                        ["step", "status"],
                    ),
                    "The list of steps.",
                ),
            },
            ["plan"],
        ),
    },
    {
        "name": "get_goal",
        "description": "Get the current goal for this thread, including status, budget, elapsed-time usage, and remaining token budget when known.",
        "inputSchema": schema({}),
    },
    {
        "name": "create_goal",
        "description": "Create a goal only when explicitly requested. Fails if an active goal exists.",
        "inputSchema": schema(
            {
                "objective": string("Required. The concrete objective to start pursuing."),
                "token_budget": {"type": "integer", "description": "Positive token budget. Omit unless explicitly requested."},
            },
            ["objective"],
        ),
    },
    {
        "name": "update_goal",
        "description": "Update the existing active goal. Use only to mark it complete or genuinely blocked.",
        "inputSchema": schema(
            {"status": {"type": "string", "enum": ["complete", "blocked"]}},
            ["status"],
        ),
    },
    {
        "name": "tool_search",
        "description": "Searches over this server's tool metadata and returns matching tools.",
        "inputSchema": schema(
            {
                "query": string("Search query for tools."),
                "limit": number("Maximum number of tools to return. Defaults to 8."),
            },
            ["query"],
        ),
    },
    {
        "name": "multi_tool_use.parallel",
        "description": "Runs multiple Codex MCP tools concurrently when their effects can safely happen in parallel.",
        "inputSchema": schema(
            {
                "tool_uses": array(
                    schema(
                        {
                            "recipient_name": string("Tool name, or namespace-qualified name such as functions.exec_command."),
                            "parameters": {"type": "object", "description": "Arguments to pass to the tool."},
                        },
                        ["recipient_name", "parameters"],
                    ),
                    "The tools to execute in parallel.",
                )
            },
            ["tool_uses"],
        ),
    },
]
