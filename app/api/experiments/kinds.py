"""Every capture experiment in the app, by slug."""

from . import (
    agent_agents, agent_endpoint, agent_infrastructure, agent_plc, custom_experiment, custom_prompts, data_collector, delay,
    good_bad_agents, scalability, temperature_change, topology_transfer,
)
from .base import Kind

KINDS: dict[str, Kind] = {
    k.slug: k
    for k in (
        data_collector.KIND,
        temperature_change.KIND,
        custom_prompts.KIND,
        scalability.KIND,
        delay.KIND,
        custom_experiment.KIND,
        topology_transfer.KIND,
        agent_infrastructure.KIND,
        agent_plc.KIND,
        agent_endpoint.KIND,
        agent_agents.KIND,
        good_bad_agents.KIND,
    )
}
