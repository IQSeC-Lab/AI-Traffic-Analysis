"""
What the agentic experiments with tasks of their own share (Agent to Infrastructure,
Agent to PLC, Agent to Endpoint): their settings, their editable tasks, how a task becomes
a MARBLE config, and what their New run form is told. Agent to LLM (topology_transfer.py)
runs MARBLE's own task files.

Their tasks can be edited, removed and added to in the New run form (task_store.py): each
experiment keeps its edits in DATA_DIR/<slug>-tasks.json.
"""

from __future__ import annotations

from itertools import combinations

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import Field

from settings import ollama_models
from storage import MARBLE_DIR

from . import task_store
from .base import RunConfig, Variant
from .topology_transfer import DEFAULT_MODEL, MARBLE_REPO, TOPOLOGIES, Topology, marble_problem

TASKS_PER_CATEGORY = 15   # as many as the published dataset uses of each MARBLE category
ROUNDS = 3                # MARBLE's max_iterations: how many times the agents plan and act again


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
    `tasks` each one's tasks as they are now and `builtin` as they ship. The form loads a
    category's tasks themselves when they are edited (GET /api/<slug>/tasks/<category>)."""
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
             "edited": tasks[slug] != builtin[slug]}
            for slug, (label, text) in categories.items()
        ],
        "editable": {"max_tasks": task_store.MAX_TASKS, "max_chars": task_store.MAX_CHARS},
        **more,
    }


# ── Editable tasks ───────────────────────────────────────────────────────────

def saved_tasks(slug: str, builtin: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Each category's tasks: what was last saved for it, or its built-in tasks."""
    return {category: task_store.saved(slug, category, tasks) for category, tasks in builtin.items()}


def task_editing(router: APIRouter, slug: str, builtin: dict[str, list[dict]], states: tuple[str, ...] = ()) -> None:
    """The routes that edit the experiment's tasks (task_store.routes). `states`: the ones a task
    can start from (Agent to PLC), one of which every task must have."""

    def clean(category: str, tasks: list[task_store.TaskIn]) -> list[dict]:
        if states and (bad := [t.state for t in tasks if t.state not in states]):
            raise HTTPException(400, f"A task starts from one of these states: {', '.join(states)}. Not {bad[0]}.")
        return [{"text": t.text, "state": t.state} if states else {"text": t.text} for t in tasks]

    task_store.routes(router, slug, builtin, lambda category: builtin[category], clean)
