"""
Agent to LLM, the first agentic experiment: MARBLE tasks solved by several agents that
all call one LLM server, and those calls are what is captured. The coordination topology
(graph, star) is an option of the run: a task is captured once under each one chosen, and
it is then the only thing that changes between that task's captures, so a classifier
trained on one topology can be tested on the other.

The experiment was first named Topology Transfer. Its slug, and so its API path and
results folder, keep that name: the runs made under it stay where they are.

The tasks and the agents come from toolbox/marble (MARBLE_DIR): marble-traffic-dataset, a fork
of MARBLE / MultiAgentBench. Its task configs are multiagentbench/output_yaml_<category>_local
for the graph topology and output_yaml_<category>_star for star. MARBLE talks to Ollama's API
(through litellm, which asks it for JSON when an agent has tools), so the model is an Ollama
model (OLLAMA_DIR), not one of the HuggingFace models the other experiments load.
marble_engine.py runs it.

The tasks can be edited, removed and added to in the New run form (task_store.py). A task is
then its text and its agents' profiles (in some categories, bug fix or medical diagnosis, the
agents hold part of the task), on top of one of MARBLE's task files, its "base", which gives
everything else: the agents' ids, their relationships and the environment of each topology.
Agent to Agents and Good Agent Bad Agent run the same tasks and share the edits.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import Field

from settings import ollama_models
from storage import MARBLE_DIR

from . import task_store
from .base import Kind, Link, RunConfig, Variant

MARBLE_REPO = "https://github.com/pooryousefshahrooz/marble-traffic-dataset"   # where toolbox/marble was copied from
DEFAULT_MODEL = "llama3.2:3b"
CONFIG_MODEL = "ollama/llama3.2:3b"   # how every task config names the model; replaced with the run's
DATASET_TASKS = 15                    # the published dataset uses tasks 1 to 15 of each category
TASK_STORE = "marble"                 # the edited tasks, shared by every experiment that runs MARBLE's (task_store.py)
EDITED_PROGRESS = "Starting the task."   # an edited task's engine_planner.initial_progress, which names the original task

# topology: (label, suffix of its config folders, the line MARBLE logs when a task completes)
TOPOLOGIES: dict[str, tuple[str, str, str]] = {
    "graph": ("Graph", "local", "Graph-based coordination simulation completed."),
    "star": ("Star", "star", "Engine simulation loop completed."),
}

# category: (label, why it can't run here). The agents run in a container on a network without
# internet, as in the other experiments.
CATEGORIES: dict[str, tuple[str, str | None]] = {
    "bargaining": ("Bargaining", None),
    "bugfix": ("Bug fix", None),
    "coding": ("Coding", None),
    "database": ("Database", "Its tasks start PostgreSQL with docker compose, which the agents' container can't do. "
                             "Agent to Infrastructure has database tasks of its own."),
    "debate": ("Debate", None),
    "deep_research": ("Deep research", None),
    "legal_review": ("Legal review", None),
    "medical_diagnosis": ("Medical diagnosis", None),
    "research": ("Research", "Its tasks fetch papers from arXiv and Semantic Scholar, and the run's network has no internet."),
    "swe_bench": ("SWE-bench", None),
}

Topology = Literal["graph", "star"]

# The TLS proxy in front of Ollama (marble_engine.PROXY_PORT), and MARBLE's record of each agent's calls to it
LLM_LINK = Link(port=11443, calls="agent_calls")


class TopologyTransferConfig(RunConfig):
    model: str = Field(DEFAULT_MODEL, pattern=ollama_models.MODEL_PATTERN,
                       description="Ollama model the agents call, downloaded in Settings.")
    topologies: list[Topology] = Field(["graph", "star"], min_length=1,
                                       description="Every task is captured once under each.")
    categories: list[str] = Field(..., min_length=1, description="MARBLE task categories (GET /api/topology-transfer/tasks).")
    tasks: list[int] = Field(list(range(1, DATASET_TASKS + 1)), min_length=1,
                             description="Task numbers run in every chosen category.")


# ── The MARBLE checkout ──────────────────────────────────────────────────────

def marble_problem() -> str | None:
    """Why the MARBLE code can't be used, if it can't."""
    if not (MARBLE_DIR / "marble" / "main.py").is_file() or not (MARBLE_DIR / "multiagentbench").is_dir():
        return (f"The MARBLE code is not at {MARBLE_DIR}. It ships with the API, in experiments/toolbox/marble: check "
                "that the folder was copied to this machine, or point MALLM_MARBLE_DIR at it and restart the API.")
    return None


def task_file(category: str, topology: str, task_id: int) -> Path:
    return MARBLE_DIR / "multiagentbench" / f"output_yaml_{category}_{TOPOLOGIES[topology][1]}" / f"task_{task_id}.yaml"


def _task_ids(category: str) -> list[int]:
    """Tasks of a category that have a config for every topology."""
    ids: set[int] | None = None
    for _, suffix, _ in TOPOLOGIES.values():
        folder = MARBLE_DIR / "multiagentbench" / f"output_yaml_{category}_{suffix}"
        found = {int(m.group(1)) for p in folder.glob("task_*.yaml") if (m := re.fullmatch(r"task_(\d+)", p.stem))}
        ids = found if ids is None else ids & found
    return sorted(ids or [])


@lru_cache(maxsize=4096)
def _read_task(path: str, mtime_ns: int) -> tuple[str, tuple[tuple[str, str], ...]]:
    """A task's description and its agents (id, profile)."""
    data = yaml.load(Path(path).read_text(), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    agents = tuple((str(a.get("agent_id")), str(a.get("profile") or "")) for a in data.get("agents") or [])
    return str((data.get("task") or {}).get("content") or "").strip(), agents


def builtin_tasks(category: str) -> list[dict]:
    """The category's tasks as MARBLE ships them: {"text", "base": the task file's number, "agents":
    [{"id", "profile"}]}, read from the graph topology's files (the text and agents are the same in each)."""
    found = []
    for task_id in _task_ids(category):
        path = task_file(category, "graph", task_id)
        text, agents = _read_task(str(path), path.stat().st_mtime_ns)
        found.append({"text": text, "base": task_id, "agents": [{"id": a, "profile": p} for a, p in agents]})
    return found


def category_tasks(category: str) -> list[dict]:
    """The category's tasks as they are now: edited (task_store.py), or MARBLE's."""
    found = task_store.rows(TASK_STORE, category)
    return builtin_tasks(category) if found is None else found


def prompts(config: TopologyTransferConfig) -> dict[int, dict]:
    """The run's tasks as its prompts, numbered in category order: {number: {"text", "category", ...}}.
    Each has the number of its task file ("base"), and an edited one its agents' profiles ("profiles"),
    so that the run's prompts.json says what ran."""
    if problem := marble_problem():
        raise ValueError(problem)
    unknown = [c for c in config.categories if c not in CATEGORIES]
    if unknown:
        raise ValueError(f"Unknown task categor{'y' if len(unknown) == 1 else 'ies'}: {', '.join(unknown)}.")
    tasks = sorted(set(config.tasks))
    if tasks[0] < 1:
        raise ValueError("Tasks are numbered from 1.")
    found: dict[int, dict] = {}
    for category in [c for c in CATEGORIES if c in config.categories]:
        label, why_not = CATEGORIES[category]
        if why_not:
            raise ValueError(f"{label} tasks can't run here. {why_not}")
        have = category_tasks(category)
        if tasks[-1] > len(have):
            raise ValueError(f"{label} has {len(have)} task{'' if len(have) == 1 else 's'}; there is no task {tasks[-1]}.")
        originals = {t["base"]: t for t in builtin_tasks(category)}
        for task_id in tasks:
            task = have[task_id - 1]
            missing = [t for t in config.topologies if not task_file(category, t, task["base"]).is_file()]
            if missing:
                raise ValueError(f"{label} has no task {task['base']} for the {' and '.join(missing)} topology.")
            if not task["text"].strip():
                raise ValueError(f"{label} task {task_id} is empty. Write it or remove it.")
            prompt = {"text": task["text"], "category": label, "marble_category": category, "task_id": task_id,
                      "agents": len(task["agents"]), "base": task["base"]}
            original = originals.get(task["base"])
            if original is None or task["text"] != original["text"] or task["agents"] != original["agents"]:
                prompt.update(edited=True, profiles=[a["profile"] for a in task["agents"]])
            found[len(found) + 1] = prompt
    if len(found) > 999:   # capture files are numbered <task>*1000 + <repetition>
        raise ValueError(f"A run takes up to 999 tasks, this one has {len(found)}.")
    return found


def task_config(task: dict, topology: str, model: str) -> str:
    """A task of the run as a MARBLE config (YAML) with the run's model: its task file, with the text and the
    agents' profiles put in when it was edited. A run from before tasks could be edited has no "base"."""
    source = task_file(task["marble_category"], topology, task.get("base", task["task_id"]))
    text = source.read_text().replace(CONFIG_MODEL, f"ollama/{model}")
    if not task.get("edited"):
        return text   # the file as it is, as the published dataset ran it
    data = yaml.safe_load(text)
    data["task_id"] = task["task_id"]
    data["task"]["content"] = task["text"]
    for agent, profile in zip(data["agents"], task["profiles"], strict=True):
        agent["profile"] = profile
    if data.get("engine_planner"):
        data["engine_planner"]["initial_progress"] = EDITED_PROGRESS
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def variants(config: TopologyTransferConfig) -> list[Variant]:
    if len(set(config.topologies)) != len(config.topologies):
        raise ValueError("A topology is listed twice.")
    # In the order the paper shows them, whatever order they were sent in
    return [
        Variant(key=t, label=TOPOLOGIES[t][0], model=config.model, columns={"topology": t})
        for t in TOPOLOGIES if t in config.topologies
    ]


def check(config: TopologyTransferConfig, variants: list[Variant]) -> int:
    """GPU memory a worker's Ollama needs for the model, which must be downloaded (Settings)."""
    return ollama_models.reserve_mb(config.model, on_gpu=config.gpus != [])


def _runner(config: RunConfig) -> type:
    from .marble_engine import MarbleExperiment   # imports the engine, which imports the kinds
    return MarbleExperiment


KIND = Kind(
    slug="topology-transfer",
    title="Agent to LLM",
    config=TopologyTransferConfig,
    variants=variants,
    variable="Topology",
    prompts=prompts,
    check=check,
    runner=_runner,
    sampled=False,
    link=LLM_LINK,
)


# ── What the New run form needs ──────────────────────────────────────────────

router = APIRouter(prefix=f"/{KIND.slug}", tags=[KIND.title])


@router.get("/tasks")
def tasks() -> dict:
    """The task categories and topologies a run can use, and whether the MARBLE code is in place."""
    problem = marble_problem()

    def category(slug: str, label: str, why_not: str | None) -> dict:
        edited = task_store.rows(TASK_STORE, slug)
        count = len(_task_ids(slug)) if edited is None else len(edited)
        return {"slug": slug, "label": label, "disabled": why_not, "about": None,
                "tasks": [] if problem else list(range(1, count + 1)),
                "edited": edited is not None and edited != builtin_tasks(slug)}

    return {
        "available": problem is None,
        "problem": problem,
        "marble_dir": str(MARBLE_DIR),
        "repo": MARBLE_REPO,
        "default_model": DEFAULT_MODEL,
        "dataset_tasks": DATASET_TASKS,
        "from_dataset": True,
        "about": "MARBLE task categories. Each task defines its own agents, usually 3 to 5.",
        "topologies": [{"key": key, "label": label} for key, (label, _, _) in TOPOLOGIES.items()],
        "categories": [category(slug, label, why_not) for slug, (label, why_not) in CATEGORIES.items()],
        "editable": {"max_tasks": task_store.MAX_TASKS, "max_chars": task_store.MAX_CHARS,
                     "shared": "Agent to LLM, Agent to Agents and Good Agent Bad Agent run these same tasks, so an edit here "
                               "changes them in all three."},
    }


def _clean(category: str, tasks: list[task_store.TaskIn]) -> list[dict]:
    """The tasks saved for a category: each on one of its task files, with that file's agents in order."""
    label = CATEGORIES[category][0]
    originals = {t["base"]: t for t in builtin_tasks(category)}
    rows = []
    for n, t in enumerate(tasks, start=1):
        original = originals.get(t.base)
        if original is None:
            raise HTTPException(400, f"{label} task {n} is based on task {t.base}, which {label} doesn't have.")
        ids = [a["id"] for a in original["agents"]]
        if [a.id for a in t.agents or []] != ids:
            raise HTTPException(400, f"{label} task {n} has the agents of task {t.base}: {', '.join(ids)}, in that order.")
        rows.append({"text": t.text, "base": t.base, "agents": [{"id": a.id, "profile": a.profile} for a in t.agents]})
    return rows


def task_editing(router: APIRouter) -> None:
    """The routes that edit MARBLE's tasks (task_store.routes), on every experiment that runs them."""
    task_store.routes(router, TASK_STORE, [slug for slug, (_, why_not) in CATEGORIES.items() if why_not is None],
                      builtin_tasks, _clean)


task_editing(router)
