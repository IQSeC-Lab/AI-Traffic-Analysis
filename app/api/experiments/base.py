"""
What every capture experiment shares, and what sets each one apart.

All experiments run the same capture (see engine.py): a fresh inference container
per prompt, a tcpdump sidecar sharing its network, and a client on an isolated
network. An experiment is defined by its settings and by the variants it compares:
the Data Collector has one, Temperature Change one per temperature, Scalability
one per model, Delay one per network condition and the Custom Experiment one per
scenario. Every prompt (and repetition) is captured once per variant.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Annotated, Callable, Literal

from pydantic import BaseModel, Field

from prompt_library import store as prompt_library
from storage import MODEL_REF_PATTERN

NAME_MAX = 60
MAX_VARIANTS = 8   # each variant gets its own color in the charts (--series-1 to --series-8)
# The prompts a run was created with, saved in its folder as {number: {"text", "category"}}.
# Results are read against these, so editing or deleting a prompt later never changes a past run.
PROMPTS_FILE = "prompts.json"

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


def library_prompts(config: RunConfig) -> dict[int, dict]:
    """The prompts of a run that takes them from the prompt library: those chosen, or all."""
    numbers = [p["number"] for p in prompt_library.all_prompts()]
    invalid = [n for n in config.prompts or [] if n not in numbers]
    if invalid:
        raise ValueError(f"Unknown prompt number(s) {invalid}. See the prompt library.")
    return prompt_library.snapshot(config.prompts or numbers)


@dataclass(frozen=True)
class Variant:
    """One setting an experiment compares. Its captures are <key>-pNN.pcap, <key>-pNN.json, ..."""

    key: str                              # unique in the run, and safe in file names
    label: str                            # how the logs and the UI name it
    model: str
    temperature: float | None = None      # None until a run is created: then the default from Settings
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
    # The run's prompts as {number: {"text", "category"}}, raising ValueError when they can't run.
    # None: prompt numbers from the prompt library (library_prompts).
    prompts: Callable[[RunConfig], dict[int, dict]] | None = None
    # Runs that don't load a HuggingFace model in the app's own server (the Data Collector on
    # Ollama, the agentic experiments) are run by a subclass of engine.Experiment:
    # GPU memory one worker needs, raising ValueError when the run can't start.
    # None: the run's HuggingFace models must be downloaded, and the largest sets it.
    check: Callable[[RunConfig, list[Variant]], int] | None = None
    # The engine.Experiment subclass for these settings. None: engine.Experiment.
    runner: Callable[[RunConfig], type | None] | None = None
    sampled: bool = True                          # False: its variants don't take the default temperature
    agentic: bool = False                         # analyzed by marble_analysis.py instead of analysis.py

    @property
    def run_label(self) -> str:
        """Docker label on everything a run creates, so cleanup only touches its own resources."""
        return f"mallm.{self.slug}.run"
