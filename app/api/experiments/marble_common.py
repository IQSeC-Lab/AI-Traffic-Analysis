"""
What the agentic experiments with tasks of their own share (Agent to Infrastructure,
Agent to PLC, Agent to Endpoint): their settings, their editable tasks, how a task becomes
a MARBLE config, and what their New run form is told. Agent to LLM (topology_transfer.py)
runs MARBLE's own task files.

Their tasks can be edited, removed and added to in the New run form, like Custom Prompts'
prompts. Each category's edited tasks are saved in DATA_DIR/<slug>-tasks.json; a category
never saved keeps its built-in tasks. A run keeps a copy of the tasks it ran (prompts.json).
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from itertools import combinations

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from settings import ollama_models
from storage import DATA_DIR, MARBLE_DIR

from .base import RunConfig, Variant
from .topology_transfer import DEFAULT_MODEL, MARBLE_REPO, TOPOLOGIES, Topology, marble_problem

TASKS_PER_CATEGORY = 15   # as many as the published dataset uses of each MARBLE category
ROUNDS = 3                # MARBLE's max_iterations: how many times the agents plan and act again
MAX_TASKS = 60            # in a category
MAX_TASK_CHARS = 4000


class TaskRunConfig(RunConfig):
    model: str = Field(DEFAULT_MODEL, pattern=ollama_models.MODEL_PATTERN,
                       description="Ollama model the agents call, downloaded in Settings.")
    topologies: list[Topology] = Field(["graph", "star"], min_length=1,
                                       description="Every task is captured once under each.")
    categories: list[str] = Field(..., min_length=1, description="Task categories (GET /api/<experiment>/tasks).")
    tasks: list[int] = Field(list(range(1, TASKS_PER_CATEGORY + 1)), min_length=1,
                             description="Task numbers run in every chosen category.")


def variants(config: TaskRunConfig) -> list[Variant]:
    if len(set(config.topologies)) != len(config.topologies):
        raise ValueError("A topology is listed twice.")
    return [
        Variant(key=t, label=TOPOLOGIES[t][0], model=config.model, columns={"topology": t})
        for t in TOPOLOGIES if t in config.topologies
    ]


def check(config: TaskRunConfig, variants: list[Variant]) -> int:
    """GPU memory a worker's Ollama needs for the model, which must be downloaded (Settings)."""
    return ollama_models.reserve_mb(config.model, on_gpu=config.gpus != [])


def prompts(config: TaskRunConfig, categories: dict[str, str], tasks: dict[str, list[dict]], agents: int) -> dict[int, dict]:
    """The run's tasks as its prompts, numbered in category order: {number: {"text", "category", ...}}.
    `categories` is {slug: label}, `tasks` the tasks of each ({"text"}, and whatever else a task holds)."""
    if problem := marble_problem():
        raise ValueError(problem)
    unknown = [c for c in config.categories if c not in categories]
    if unknown:
        raise ValueError(f"Unknown task categor{'y' if len(unknown) == 1 else 'ies'}: {', '.join(unknown)}.")
    numbers = sorted(set(config.tasks))
    if numbers[0] < 1:
        raise ValueError("Tasks are numbered from 1.")
    found: dict[int, dict] = {}
    for category in [c for c in categories if c in config.categories]:
        label, have = categories[category], tasks[category]
        if numbers[-1] > len(have):
            raise ValueError(f"{label} has {len(have)} task{'' if len(have) == 1 else 's'}; there is no task {numbers[-1]}.")
        for task_id in numbers:
            task = have[task_id - 1]
            if not task["text"].strip():
                raise ValueError(f"{label} task {task_id} is empty. Write it or remove it.")
            found[len(found) + 1] = {
                **task,
                "category": label,
                "marble_category": category,
                "task_id": task_id,
                "agents": agents,
            }
    return found


def task_config(*, scenario: str, task: dict, topology: str, model: str, environment: dict, content: str,
                output_format: str, agents: list[tuple[str, str]]) -> str:
    """A task as a MARBLE config (YAML), in the shape of MARBLE's own task files. `agents` is
    [(id, profile)]; every one of them works with every other."""
    llm = f"ollama/{model}"
    return yaml.safe_dump({
        "scenario": scenario,
        "task_id": task["task_id"],
        "coordinate_mode": topology,
        "relationships": [[a, b, "collaborate with"] for (a, _), (b, _) in combinations(agents, 2)],
        "llm": llm,
        "environment": {**environment, "max_iterations": ROUNDS},
        "communication": False,
        "task": {"content": content, "output_format": output_format},
        "agents": [{"type": "BaseAgent", "agent_id": agent, "profile": profile, "llm": llm} for agent, profile in agents],
        "memory": {"type": "BaseMemory"},
        "metrics": {"response_time": True, "evaluate_llm": llm},
        "output": {"file_path": f"result/{scenario}_output.jsonl"},
        "engine_planner": {"initial_progress": "Starting the simulation."},
    }, sort_keys=False, allow_unicode=True, width=120)


def catalog(about: str, categories: dict[str, tuple[str, str]], tasks: dict[str, list[dict]],
            builtin: dict[str, list[dict]], **more) -> dict:
    """What the New run form needs: `categories` is {slug: (label, what the form says about it)},
    `tasks` each one's tasks as they are now and `builtin` as they ship."""
    problem = marble_problem()
    return {
        "available": problem is None,
        "problem": problem,
        "marble_dir": str(MARBLE_DIR),
        "repo": MARBLE_REPO,
        "default_model": DEFAULT_MODEL,
        "dataset_tasks": min(len(t) for t in builtin.values()),
        "from_dataset": False,
        "about": about,
        "topologies": [{"key": key, "label": label} for key, (label, _, _) in TOPOLOGIES.items()],
        "categories": [
            {"slug": slug, "label": label, "disabled": None, "about": text, "tasks": list(range(1, len(tasks[slug]) + 1)),
             "texts": tasks[slug], "builtin": builtin[slug]}
            for slug, (label, text) in categories.items()
        ],
        "editable": {"max_tasks": MAX_TASKS, "max_chars": MAX_TASK_CHARS},
        **more,
    }


# ── Editable tasks ───────────────────────────────────────────────────────────

_lock = threading.Lock()


def _tasks_file(slug: str):
    return DATA_DIR / f"{slug}-tasks.json"


def _saved(slug: str) -> dict:
    try:
        data = json.loads(_tasks_file(slug).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def saved_tasks(slug: str, builtin: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Each category's tasks: what was last saved for it, or its built-in tasks."""
    saved = _saved(slug)

    def valid(found) -> bool:
        return isinstance(found, list) and all(isinstance(t, dict) and isinstance(t.get("text"), str) for t in found)

    return {category: saved[category] if valid(saved.get(category)) else tasks for category, tasks in builtin.items()}


class TaskText(BaseModel):
    text: str = Field(..., max_length=MAX_TASK_CHARS)
    state: str | None = None   # Agent to PLC: the state of the plant the task starts from


class SavedTasks(BaseModel):
    tasks: list[TaskText] = Field(..., max_length=MAX_TASKS)


def task_editing(router: APIRouter, slug: str, builtin: dict[str, list[dict]], catalog: Callable[[], dict],
                 states: tuple[str, ...] = ()) -> None:
    """PUT /api/<slug>/tasks/<category>: save a category's tasks, answered with the catalog. Drafts
    are fine: an empty task is only refused when a run starts. `states`: the ones a task can start from."""

    @router.put("/tasks/{category}")
    def put_tasks(category: str, body: SavedTasks) -> dict:
        if category not in builtin:
            raise HTTPException(404, f"Unknown task category: {category}")
        if states and (bad := [t.state for t in body.tasks if t.state not in states]):
            raise HTTPException(400, f"A task starts from one of these states: {', '.join(states)}. Not {bad[0]}.")
        rows = [{"text": t.text, "state": t.state} if states else {"text": t.text} for t in body.tasks]
        with _lock:
            data = _saved(slug)
            data[category] = rows
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = _tasks_file(slug).with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            os.replace(tmp, _tasks_file(slug))
        return catalog()
