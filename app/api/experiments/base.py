"""
What every capture experiment shares, and what sets each one apart.

All experiments run the same capture (see engine.py): a fresh inference container
per prompt, a tcpdump sidecar sharing its network, and a client on an isolated
network. An experiment is defined by its settings and by the variants it compares:
the Data Collector has one, Temperature Change one per temperature, Scalability
one per model and Delay one per network condition. Every prompt (and repetition)
is captured once per variant.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Annotated, Callable, Literal

from pydantic import BaseModel, Field

from storage import MODEL_REF_PATTERN

NAME_MAX = 60
MAX_VARIANTS = 8   # each variant gets its own color in the charts (--series-1 to --series-8)

ModelRef = Annotated[
    str,
    Field(pattern=MODEL_REF_PATTERN,
          description="HuggingFace model id, or a folder name in the models directory. Must be downloaded."),
]


class RunConfig(BaseModel):
    """Settings every experiment has."""

    prompts: list[int] | None = Field(
        None, description="Prompt numbers from the prompt library (GET /api/prompts). Omit to run all."
    )
    repeat: int | None = Field(
        None, ge=1, description="Run each prompt this many times. Omit to run each once."
    )
    gpus: list[int] | Literal["auto"] = Field(
        "auto",
        description='"auto" spreads the workers over the GPUs with room; a list uses those GPUs '
                    "(see GET /api/system); an empty list runs on the CPU.",
    )
    split_model: bool = Field(
        False,
        description="With a list of GPUs: false runs each worker on one of them in turn (one copy of the "
                    "model per GPU); true splits every worker's model across all of them, for models "
                    "too large for one GPU.",
    )
    max_tokens: int = Field(2048, ge=1)
    workers: int | None = Field(
        None, ge=1, le=16,
        description="Model instances running in parallel, each with its own containers, network and packet "
                    "capture; the captures are divided evenly between them. Default: one per listed GPU "
                    "(unless split_model), otherwise 1.",
    )
    name: str | None = Field(None, max_length=NAME_MAX, description="Optional name to recognize the run by.")


@dataclass(frozen=True)
class Variant:
    """One setting an experiment compares. Its captures are <key>-pNN.pcap, <key>-pNN.json, ..."""

    key: str                              # unique in the run, and safe in file names
    label: str                            # how the logs and the UI name it
    model: str
    temperature: float | None = None      # None: the inference server's default (0.7)
    network: dict | None = None           # tc netem on the server's egress: delay_ms, jitter_ms, distribution
    columns: dict = field(default_factory=dict)   # its settings, as columns of the metrics CSV

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Variant:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True)
class Kind:
    """An experiment: its URL and folder name, its settings and the variants a run compares."""

    slug: str                                     # /api/<slug>, <results folder>/<slug>/<run id>
    title: str                                    # "Data Collector"
    config: type[RunConfig]
    variants: Callable[[RunConfig], list[Variant]]   # raises ValueError for settings that can't run
    variable: str | None = None                   # what the variants vary ("Temperature"); None with one variant

    @property
    def run_label(self) -> str:
        """Docker label on everything a run creates, so cleanup only touches its own resources."""
        return f"mallm.{self.slug}.run"
