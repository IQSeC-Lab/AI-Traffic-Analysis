"""
Agent to PLC: several agents carry out a request on a PLC that runs a small brewery, and their
connections to it (OPC UA, encrypted) are what is captured. Agent to LLM captures their calls
to the model instead.

The PLC is a simulated one (plc_plant.py): Microsoft's OPC PLC with the brewery loaded from a
nodes file and its physics running beside it, started again for every task on the worker's own
network, so each task starts from the same values. The tasks are requests on it, nine kinds of
two: monitor, compare, explore, control, closed loop, incident, history, anomaly and setpoints.
The agents, the model and the two coordination topologies are MARBLE's, as in Agent to LLM,
and plc_engine.py runs them.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import Field

from . import marble_common as common
from . import plc_plant as plant
from .base import Kind, Link, RunConfig

ENV_TYPE = "PLC"   # the environment toolbox/marble_plc.py adds to MARBLE

# OPC UA is not TLS: its own setup messages (Hello, Acknowledge, OpenSecureChannel and
# CloseSecureChannel, each one whole message: F) are left out of the measurements like a TLS handshake.
PLC_LINK = Link(port=plant.PORT, calls="tool_calls", setup=(b"HELF", b"ACKF", b"OPNF", b"CLOF"))


# Each category's tasks as they ship, with the state of the brewery each starts from; the New run
# form can edit them (marble_common.saved_tasks)
BUILTIN = {category: [{"text": text, "state": state} for text, state in tasks] for category, tasks in plant.TASKS.items()}


class PlcConfig(common.TaskRunConfig):
    tasks: list[int] = Field(list(range(1, plant.TASKS_PER_CATEGORY + 1)), min_length=1,
                             description="Task numbers run in every chosen category.")


def prompts(config: PlcConfig) -> dict[int, dict]:
    """The run's tasks, each with the state of the brewery it starts from ("state")."""
    return common.prompts(config, {slug: label for slug, (label, _) in plant.CATEGORIES.items()},
                          common.saved_tasks(KIND.slug, BUILTIN), len(plant.AGENTS))


def task_config(task: dict, topology: str, model: str) -> str:
    return common.task_config(
        scenario="plc", task=task, topology=topology, model=model,
        environment={"type": ENV_TYPE, "name": "PLC Environment"},
        content=plant.task_text(task["text"], task["marble_category"]),
        output_format="Say in a few sentences what was done on the PLC and what it holds now.",
        agents=plant.AGENTS,
    )


def _runner(config: RunConfig) -> type:
    from .plc_engine import PlcExperiment   # imports the engine, which imports the kinds
    return PlcExperiment


KIND = Kind(
    slug="agent-to-plc",
    title="Agent to PLC",
    config=PlcConfig,
    variants=common.variants,
    variable="Topology",
    prompts=prompts,
    check=common.check,
    runner=_runner,
    sampled=False,
    link=PLC_LINK,
)


# ── What the New run form needs ──────────────────────────────────────────────

router = APIRouter(prefix=f"/{KIND.slug}", tags=[KIND.title])


@router.get("/tasks")
def tasks() -> dict:
    """The kinds of request and the topologies a run can use, and whether the MARBLE code is in place."""
    return common.catalog(
        "Requests on a simulated PLC (OPC UA) that runs a small brewery: three fermenters, a bottling line, a recipe "
        "and a stacklight, with physics that moves them, plus the simulator's own boiler. It is started again for "
        f"every task. The same {len(plant.AGENTS)} agents work on each one.",
        plant.CATEGORIES, common.saved_tasks(KIND.slug, BUILTIN), BUILTIN,
        states=list(plant.STATES),
    )


common.task_editing(router, KIND.slug, BUILTIN, states=plant.STATES)
