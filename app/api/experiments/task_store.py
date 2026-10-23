"""
The editable tasks of the agentic experiments, kept like Custom Prompts' prompts: the New run
form can edit, remove and add to a category's tasks, and each category's edited tasks are saved
in DATA_DIR/<name>-tasks.json. A category never saved, or restored, keeps its built-in tasks.
A run keeps a copy of the tasks it ran (prompts.json), so edits only change the runs after them.

The experiments with tasks of their own (marble_common.py) each keep a file; the ones that run
MARBLE's task files (topology_transfer.py) share one, since they run the same tasks.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Collection

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from storage import DATA_DIR

MAX_TASKS = 200          # in a category: MARBLE's bargaining and coding have 100
MAX_CHARS = 20_000       # of a task's text, or of an agent's profile (MARBLE's bug fix profiles hold the bug's whole spec)

_lock = threading.Lock()


def _file(name: str):
    return DATA_DIR / f"{name}-tasks.json"


def _load(name: str) -> dict:
    try:
        data = json.loads(_file(name).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def rows(name: str, category: str) -> list[dict] | None:
    """The category's tasks as last saved, or None when it has its built-in ones."""
    found = _load(name).get(category)
    if isinstance(found, list) and all(isinstance(t, dict) and isinstance(t.get("text"), str) for t in found):
        return found
    return None


def saved(name: str, category: str, builtin: list[dict]) -> list[dict]:
    """The category's tasks: what was last saved for it, or `builtin`."""
    found = rows(name, category)
    return builtin if found is None else found


def _write(name: str, category: str, rows: list[dict] | None) -> None:
    """Save the category's tasks, or forget them (None) so it has its built-in ones again."""
    with _lock:
        data = _load(name)
        if rows is None:
            data.pop(category, None)
        else:
            data[category] = rows
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _file(name).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp, _file(name))


class Agent(BaseModel):
    id: str = Field(..., max_length=60)
    profile: str = Field(..., max_length=MAX_CHARS)


class TaskIn(BaseModel):
    text: str = Field(..., max_length=MAX_CHARS)
    state: str | None = None           # Agent to PLC: the state of the plant the task starts from
    base: int | None = None            # MARBLE: the task file the agents and setup come from
    agents: list[Agent] | None = None  # MARBLE: those agents, with their profiles as edited


class TasksIn(BaseModel):
    tasks: list[TaskIn] = Field(..., max_length=MAX_TASKS)


def routes(router: APIRouter, name: str, categories: Collection[str], builtin: Callable[[str], list[dict]],
           clean: Callable[[str, list[TaskIn]], list[dict]]) -> None:
    """GET, PUT and DELETE /api/<slug>/tasks/<category>: a category's tasks, saving them (drafts are
    fine: an empty task is only refused when a run starts), and restoring the built-in ones.
    `clean` turns the tasks sent into the rows saved, raising HTTPException when they can't be."""

    def known(category: str) -> None:
        if category not in categories:
            raise HTTPException(404, f"Unknown task category: {category}")

    @router.get("/tasks/{category}")
    def get_tasks(category: str) -> dict:
        """The category's tasks, and what a new one starts from when there are none to copy."""
        known(category)
        found = builtin(category)
        return {"tasks": saved(name, category, found), "template": {**found[0], "text": ""} if found else {"text": ""}}

    @router.put("/tasks/{category}")
    def put_tasks(category: str, body: TasksIn) -> dict:
        # shortcut: the whole category is sent on every save (~1.5 MB for MARBLE's bargaining); save one task at a time if that gets slow
        known(category)
        _write(name, category, clean(category, body.tasks))
        return {"saved": len(body.tasks)}

    @router.delete("/tasks/{category}")
    def restore_tasks(category: str) -> dict:
        """Forget the category's edits: it has its built-in tasks again, which are returned."""
        known(category)
        _write(name, category, None)
        return {"tasks": builtin(category)}
