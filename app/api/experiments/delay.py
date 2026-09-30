"""
Experiment 6, ported from 6-Delay: the capture under injected network delay and jitter.

Linux tc netem delays everything the inference container sends (the response stream
included), applied from a sidecar sharing its network before the capture starts, as
in 6-Delay/main.py. The capture sees packets after the delay, so both the PCAP and
the client's timing show it. A run compares several conditions, typically no delay
against one or more delays.
"""

from typing import Literal

from pydantic import BaseModel, Field

from storage import model_dir_name

from .base import MAX_VARIANTS, Kind, ModelRef, RunConfig, Variant

MAX_MS = 10_000


class NetworkCondition(BaseModel):
    delay_ms: int = Field(0, ge=0, le=MAX_MS, description="Added to every packet the inference server sends.")
    jitter_ms: int = Field(0, ge=0, le=MAX_MS, description="Random variation around the delay. Needs a delay.")
    distribution: Literal["normal", "pareto", "paretonormal"] = Field(
        "normal", description="Shape of the jitter. Only used with jitter."
    )


class DelayConfig(RunConfig):
    model: ModelRef
    conditions: list[NetworkCondition] = Field(
        default_factory=lambda: [NetworkCondition(), NetworkCondition(delay_ms=500, jitter_ms=50)],
        min_length=1,
        max_length=MAX_VARIANTS,
        description="Network conditions to compare. Every prompt is captured once under each. "
                    "A condition with no delay and no jitter leaves the network as it is.",
    )


def netem_args(network: dict) -> list[str]:
    """Arguments after `tc qdisc add dev eth0 root netem`. iproute2 rejects a distribution
    without both a delay and a jitter, so it is only passed with jitter."""
    args = ["delay", f"{network['delay_ms']}ms"]
    if network["jitter_ms"]:
        args += [f"{network['jitter_ms']}ms", "distribution", network["distribution"]]
    return args


def _describe(c: NetworkCondition) -> tuple[str, str]:
    """(label, file name part) of a condition."""
    if not c.delay_ms:
        return "No delay", "d0ms"
    if not c.jitter_ms:
        return f"{c.delay_ms} ms", f"d{c.delay_ms}ms"
    return (f"{c.delay_ms} ms ± {c.jitter_ms} ms, {c.distribution}",
            f"d{c.delay_ms}ms-j{c.jitter_ms}ms-{c.distribution}")


def variants(config: DelayConfig) -> list[Variant]:
    base = model_dir_name(config.model)
    found: list[Variant] = []
    for c in config.conditions:
        if c.jitter_ms and not c.delay_ms:
            raise ValueError(f"A jitter of {c.jitter_ms} ms needs a delay. Set a delay for that condition.")
        label, part = _describe(c)
        key = f"{base}-{part}"
        if any(v.key == key for v in found):
            raise ValueError(f"The condition {label} is listed twice.")
        network = c.model_dump() if c.delay_ms else None
        found.append(Variant(
            key=key,
            label=label,
            model=config.model,
            network=network,
            columns={
                "delay_ms": c.delay_ms,
                "jitter_ms": c.jitter_ms,
                "distribution": c.distribution if c.jitter_ms else None,
            },
        ))
    return found


KIND = Kind(
    slug="delay",
    title="Delay",
    config=DelayConfig,
    variants=variants,
    variable="Network",
)
