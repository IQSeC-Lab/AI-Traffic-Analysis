"""
Agent to Infrastructure: several agents carry out a request on a database, and their
connections to the database are what is captured (Agent to LLM, topology_transfer.py,
captures their calls to the model instead).

The database is a mock one (store_db.py): a small online store in PostgreSQL, created
again for every task on the worker's own network, so each task starts from the same rows.
The tasks are requests on it, grouped by what they do: look rows up, insert, update or
delete them, or report over many. The agents, the model and the two coordination
topologies are MARBLE's, as in Agent to LLM, and infra_engine.py runs them.

MARBLE's own database tasks (its `database` category) are another thing, the diagnosis of
a slow database, and are not used here.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import marble_common as common
from . import store_db
from .base import Kind, Link, RunConfig

ENV_TYPE = "Infrastructure"   # the environment toolbox/marble_infra.py adds to MARBLE

# What a request does to the database: (label, what the form says about it)
CATEGORIES: dict[str, tuple[str, str]] = {
    "lookup": ("Lookup", "Read one row or a few"),
    "insert": ("Insert", "Add new rows"),
    "update": ("Update", "Change rows that exist"),
    "delete": ("Delete", "Remove rows"),
    "report": ("Report", "Read and summarize many rows"),
}

# A PostgreSQL client asks for encryption in the clear before the TLS handshake: its SSLRequest
# (or GSSENCRequest) and the server's one-byte answer. They are left out of the measurements
# like the handshake itself.
DB_LINK = Link(
    port=store_db.PORT,
    calls="tool_calls",
    preamble=(b"\x00\x00\x00\x08\x04\xd2\x16\x2f", b"\x00\x00\x00\x08\x04\xd2\x16\x30", b"S", b"N"),
)


class InfrastructureConfig(common.TaskRunConfig):
    pass


def prompts(config: InfrastructureConfig) -> dict[int, dict]:
    return common.prompts(config, {slug: label for slug, (label, _) in CATEGORIES.items()}, store_db.TASKS, len(store_db.AGENTS))


def task_config(task: dict, topology: str, model: str) -> str:
    return common.task_config(
        scenario="infrastructure", task=task, topology=topology, model=model,
        environment={"type": ENV_TYPE, "name": "Infrastructure Environment"},
        content=store_db.task_text(task["text"]),
        output_format="Say in a few sentences what was done on the database and what it holds now.",
        agents=store_db.AGENTS,
    )


def _runner(config: RunConfig) -> type:
    from .infra_engine import InfrastructureExperiment   # imports the engine, which imports the kinds
    return InfrastructureExperiment


KIND = Kind(
    slug="agent-to-infrastructure",
    title="Agent to Infrastructure",
    config=InfrastructureConfig,
    variants=common.variants,
    variable="Topology",
    prompts=prompts,
    check=common.check,
    runner=_runner,
    sampled=False,
    link=DB_LINK,
)


# ── What the New run form needs ──────────────────────────────────────────────

router = APIRouter(prefix=f"/{KIND.slug}", tags=[KIND.title])


@router.get("/tasks")
def tasks() -> dict:
    """The kinds of request and the topologies a run can use, and whether the MARBLE code is in place."""
    rows = store_db.rows()
    return common.catalog(
        f"Requests on a mock online store in PostgreSQL ({rows['customers']} customers, {rows['products']} products, "
        f"{rows['orders']} orders), created again for every task. The same {len(store_db.AGENTS)} agents work on each one.",
        CATEGORIES,
    )
