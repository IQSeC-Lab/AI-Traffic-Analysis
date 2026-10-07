"""
Topology Transfer, the first agentic experiment: MARBLE tasks solved by several agents
that all call one LLM server, captured once per coordination topology. The topology is
the only thing that changes between a task's captures, so a classifier trained on one
can be tested on the other.

The tasks and the agents come from toolbox/marble (MARBLE_DIR): marble-traffic-dataset, a fork
of MARBLE / MultiAgentBench. Its task configs are multiagentbench/output_yaml_<category>_local
for the graph topology and output_yaml_<category>_star for star. MARBLE talks to Ollama and
uses tool calls, so the model is an Ollama model (OLLAMA_DIR), not one of the HuggingFace
models the other experiments load. marble_engine.py runs it.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter
from pydantic import Field

from settings import ollama_models
from storage import MARBLE_DIR

from .base import Kind, RunConfig, Variant

MARBLE_REPO = "https://github.com/pooryousefshahrooz/marble-traffic-dataset"   # where toolbox/marble was copied from
DEFAULT_MODEL = "llama3.2:3b"
CONFIG_MODEL = "ollama/llama3.2:3b"   # how every task config names the model; replaced with the run's
DATASET_TASKS = 15                    # the published dataset uses tasks 1 to 15 of each category

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
    "database": ("Database", "Its tasks start PostgreSQL with docker compose, which the agents' container can't do."),
    "debate": ("Debate", None),
    "deep_research": ("Deep research", None),
    "legal_review": ("Legal review", None),
    "medical_diagnosis": ("Medical diagnosis", None),
    "research": ("Research", "Its tasks fetch papers from arXiv and Semantic Scholar, and the run's network has no internet."),
    "swe_bench": ("SWE-bench", None),
}

Topology = Literal["graph", "star"]


class TopologyTransferConfig(RunConfig):
    model: str = Field(DEFAULT_MODEL, pattern=ollama_models.MODEL_PATTERN,
                       description="Ollama model the agents call, downloaded in Settings. It must support tool calls.")
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
def _read_task(path: str, mtime_ns: int) -> tuple[str, int]:
    """A task's description and its number of agents."""
    data = yaml.load(Path(path).read_text(), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    return str((data.get("task") or {}).get("content") or "").strip(), len(data.get("agents") or [])


def prompts(config: TopologyTransferConfig) -> dict[int, dict]:
    """The run's tasks as its prompts, numbered in category order: {number: {"text", "category", ...}}."""
    if problem := marble_problem():
        raise ValueError(problem)
    unknown = [c for c in config.categories if c not in CATEGORIES]
    if unknown:
        raise ValueError(f"Unknown task categor{'y' if len(unknown) == 1 else 'ies'}: {', '.join(unknown)}.")
    tasks = sorted(set(config.tasks))
    found: dict[int, dict] = {}
    for category in [c for c in CATEGORIES if c in config.categories]:
        label, why_not = CATEGORIES[category]
        if why_not:
            raise ValueError(f"{label} tasks can't run here. {why_not}")
        for task_id in tasks:
            missing = [t for t in config.topologies if not task_file(category, t, task_id).is_file()]
            if missing:
                raise ValueError(f"{label} has no task {task_id} for the {' and '.join(missing)} topology.")
            path = task_file(category, config.topologies[0], task_id)
            text, agents = _read_task(str(path), path.stat().st_mtime_ns)
            found[len(found) + 1] = {
                "text": text, "category": label, "marble_category": category, "task_id": task_id, "agents": agents,
            }
    if len(found) > 999:   # capture files are numbered <task>*1000 + <repetition>
        raise ValueError(f"A run takes up to 999 tasks, this one has {len(found)}.")
    return found


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
    title="Topology Transfer",
    config=TopologyTransferConfig,
    variants=variants,
    variable="Topology",
    prompts=prompts,
    check=check,
    runner=_runner,
    sampled=False,
    agentic=True,
)


# ── What the New run form needs ──────────────────────────────────────────────

router = APIRouter(prefix=f"/{KIND.slug}", tags=[KIND.title])


@router.get("/tasks")
def tasks() -> dict:
    """The task categories and topologies a run can use, and whether the MARBLE code is in place."""
    problem = marble_problem()
    return {
        "available": problem is None,
        "problem": problem,
        "marble_dir": str(MARBLE_DIR),
        "repo": MARBLE_REPO,
        "default_model": DEFAULT_MODEL,
        "dataset_tasks": DATASET_TASKS,
        "topologies": [{"key": key, "label": label} for key, (label, _, _) in TOPOLOGIES.items()],
        "categories": [
            {"slug": slug, "label": label, "disabled": why_not, "tasks": [] if problem else _task_ids(slug)}
            for slug, (label, why_not) in CATEGORIES.items()
        ],
    }

