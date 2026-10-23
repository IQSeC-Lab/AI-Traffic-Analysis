"""
Agent to Agents: several agents work on a MARBLE task together, each in a container of its
own, and what they say to each other is what is captured.

In MARBLE the agents of a task are objects in one process, so when one talks to another
nothing crosses the network (Agent to LLM captures only their calls to the model). Here each
agent runs on its own and talks to the others over A2A, the Agent2Agent protocol: JSON-RPC
over HTTPS, one connection per message (toolbox/marble_a2a.py). agents_engine.py runs them.

The tasks are MARBLE's own, the same files as Agent to LLM's, in the categories whose agents
share nothing but the task, so talking to each other is all they do. The topology is MARBLE's
graph only: every agent plans its own next step and starts its own conversations, with no one
in the middle. In the published dataset a 3B model mostly answered alone (in most of those
tasks no agent sent a single message), so every agent is told to work through the others
(task_config), as the agents of the other experiments are told to use their tools.
"""

from __future__ import annotations

from typing import Literal

import yaml
from fastapi import APIRouter
from pydantic import Field

from . import marble_common as common
from . import topology_transfer as marble
from .base import Kind, Link, RunConfig

TOPOLOGY = "graph"
A2A_PORT = 8443   # where every agent answers the others (toolbox/marble_a2a.py)

# MARBLE's categories whose agents act in one shared environment: as processes of their own,
# each agent would have a copy of it
SHARED_STATE = {
    "bargaining": "Its agents act in one simulated world, and agents in separate containers would each have their own.",
    "coding": "Its agents write files to one shared workspace, which agents in separate containers don't have.",
}

# Every message is its own TLS connection to the agent it is for; its sender is in the message log
MESSAGE_LINK = Link(port=A2A_PORT, calls="tool_calls")


class AgentsConfig(marble.TopologyTransferConfig):
    topologies: list[Literal["graph"]] = Field([TOPOLOGY], min_length=1,
                                               description="Graph only: every agent plans its own steps and talks to the others.")


def prompts(config: AgentsConfig) -> dict[int, dict]:
    for slug in config.categories:
        if slug in SHARED_STATE:
            raise ValueError(f"{marble.CATEGORIES[slug][0]} tasks can't run here. {SHARED_STATE[slug]}")
    return marble.prompts(config)


def task_config(marble_config: str) -> str:
    """A MARBLE task config (YAML, with the run's model) as these agents run it: each told to
    work as a team by messaging the others, and at most common.ROUNDS rounds, as in the other experiments with
    tasks of their own (every turn of a conversation is a model call)."""
    data = yaml.safe_load(marble_config)
    for agent in data.get("agents") or []:
        me = agent["agent_id"]
        agent["profile"] = (f"{str(agent.get('profile') or '').strip()} {me} is on a team with the other agents and does the "
                            f"task with them by messaging them: {me} always answers with a call to new_communication_session, "
                            "to share what it has found or to ask a teammate for their part, never on its own.")
    environment = data.setdefault("environment", {})
    environment["max_iterations"] = min(int(environment.get("max_iterations") or common.ROUNDS), common.ROUNDS)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def _runner(config: RunConfig) -> type:
    from .agents_engine import AgentsExperiment   # imports the engine, which imports the kinds
    return AgentsExperiment


KIND = Kind(
    slug="agent-to-agents",
    title="Agent to Agents",
    config=AgentsConfig,
    variants=marble.variants,
    prompts=prompts,
    check=marble.check,
    runner=_runner,
    sampled=False,
    link=MESSAGE_LINK,
)


# ── What the New run form needs ──────────────────────────────────────────────

router = APIRouter(prefix=f"/{KIND.slug}", tags=[KIND.title])


@router.get("/tasks")
def tasks() -> dict:
    """Agent to LLM's task categories, with the graph topology only, and whether the MARBLE code is in place."""
    found = marble.tasks()
    found["about"] = ("MARBLE task categories, as in Agent to LLM. Each task defines its own agents, 3 or 4, and every "
                      "one of them runs in its own container.")
    found["topologies"] = [t for t in found["topologies"] if t["key"] == TOPOLOGY]
    for category in found["categories"]:
        category["disabled"] = category["disabled"] or SHARED_STATE.get(category["slug"])
    return found
