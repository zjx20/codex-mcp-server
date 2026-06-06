from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class StateStore:
    def __init__(self, cwd: Path) -> None:
        default_path = cwd / ".codex_mcp_state.json"
        self.path = Path(os.environ.get("CODEX_MCP_STATE", default_path)).expanduser()
        self.data: dict[str, Any] = {"plan": [], "goal": None}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(loaded, dict):
            self.data.update(loaded)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def update_plan(self, plan: list[dict[str, str]], explanation: str | None) -> dict[str, Any]:
        in_progress = [item for item in plan if item.get("status") == "in_progress"]
        if len(in_progress) > 1:
            raise ValueError("At most one plan item can be in_progress at a time.")
        now = time.time()
        self.data["plan"] = plan
        self.data["plan_updated_at"] = now
        if explanation is not None:
            self.data["plan_explanation"] = explanation
        self.save()
        return {
            "status": "ok",
            "plan": plan,
            "explanation": explanation,
            "updated_at": now,
        }

    def get_goal(self) -> dict[str, Any]:
        goal = self.data.get("goal")
        if not goal:
            return {"status": "none", "goal": None}
        now = time.time()
        started = goal.get("created_at") or now
        token_budget = goal.get("token_budget")
        tokens_used = goal.get("tokens_used", 0)
        remaining = None
        if isinstance(token_budget, int):
            remaining = max(token_budget - int(tokens_used), 0)
        return {
            **goal,
            "elapsed_seconds": max(now - float(started), 0.0),
            "tokens_remaining": remaining,
        }

    def create_goal(self, objective: str, token_budget: int | None) -> dict[str, Any]:
        current = self.data.get("goal")
        if current and current.get("status") == "active":
            raise ValueError("A goal already exists; use update_goal to finish it first.")
        if token_budget is not None and token_budget <= 0:
            raise ValueError("token_budget must be a positive integer when provided.")
        now = time.time()
        goal = {
            "status": "active",
            "objective": objective,
            "token_budget": token_budget,
            "tokens_used": 0,
            "created_at": now,
            "updated_at": now,
        }
        self.data["goal"] = goal
        self.save()
        return self.get_goal()

    def update_goal(self, status: str) -> dict[str, Any]:
        if status not in {"complete", "blocked"}:
            raise ValueError('status must be "complete" or "blocked".')
        goal = self.data.get("goal")
        if not goal or goal.get("status") != "active":
            raise ValueError("No active goal exists.")
        goal["status"] = status
        goal["updated_at"] = time.time()
        goal["finished_at"] = goal["updated_at"]
        self.data["goal"] = goal
        self.save()
        return self.get_goal()
