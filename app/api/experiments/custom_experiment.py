"""
The Custom Experiment: a capture run with every setting the other experiments have.

It is not a port of one of the repo's scripts. A run is a list of scenarios, each
with its own model, sampling temperature and network condition, and every prompt is
captured once per scenario. So a run can repeat any of the other experiments, cross
them (two models under a delay, a temperature sweep on each) or be a single
scenario with everything set by hand.

Its prompts come from the prompt library, or are written for the experiment and
sent exactly as written, as in Custom Prompts. The written ones are its own, saved
in DATA_DIR/custom-experiment-prompts.json.
"""

from typing import Literal

from pydantic import BaseModel, Field

from settings import store as settings_store
from storage import DATA_DIR, model_dir_name

from .base import MAX_VARIANTS, NAME_MAX, Kind, ModelRef, RunConfig, Variant, library_prompts
from .custom_prompts import MAX_PROMPTS, PromptText, numbered, saved_prompts, saved_prompts_router
from .delay import NetworkCondition, describe

SAVED_FILE = DATA_DIR / "custom-experiment-prompts.json"


class Scenario(BaseModel):
    model: ModelRef
    temperature: float | None = Field(
        None, ge=0, le=2,
        description="Sampling temperature, 0 to 2 (0 is greedy decoding). Omit to use the default from Settings.",
    )
    network: NetworkCondition = Field(
        default_factory=NetworkCondition,
        description="Delay and jitter added to everything the inference server sends. None by default.",
    )
    label: str | None = Field(
        None, max_length=NAME_MAX,
        description="How the results name the scenario. Omit to name it by what sets it apart from the others.",
    )


class CustomExperimentConfig(RunConfig):
    scenarios: list[Scenario] = Field(
        ...,
        min_length=1,
        max_length=MAX_VARIANTS,
        description="The scenarios to compare. Every prompt is captured once in each.",
    )
    prompt_source: Literal["library", "written"] = Field(
        "library",
        description='"library": the prompt library numbers in `prompts`, all of them when omitted. '
                    '"written": the prompts themselves, in `prompt_texts`.',
    )
    prompt_texts: list[PromptText] | None = Field(
        None,
        min_length=1,
        max_length=MAX_PROMPTS,
        description='With prompt_source "written": the prompts, sent exactly as given and numbered from 1 in '
                    "this order. Omit to use the experiment's saved prompts (GET /api/custom-experiment/prompts).",
    )


def _labels(scenarios: list[Scenario], temperatures: list[float]) -> list[str]:
    """How the results name each scenario: its own label, or what sets it apart from the others
    (model, temperature, network condition). A scenario on its own is named by all three."""
    models = [s.model for s in scenarios]
    short = [m.split("/")[-1] for m in models]
    if len(set(short)) < len(set(models)):   # the same model name from two organizations
        short = models
    parts = [short, temperatures, [describe(s.network)[0] for s in scenarios]]
    differing = [p for p in parts if len(set(p)) > 1] or parts
    # Charts have little room for a label: the temperature is only spelled out when it is all there is
    temperature = "T {:g}" if len(differing) > 1 else "Temperature {:g}"
    names = [[temperature.format(t) for t in p] if p is temperatures else p for p in differing]
    return [(s.label or "").strip() or " · ".join(p[i] for p in names) for i, s in enumerate(scenarios)]


def variants(config: CustomExperimentConfig) -> list[Variant]:
    # Fixed here and not left to the engine, so a scenario's file names and label say what it sampled at
    default = settings_store.default_temperature()
    temperatures = [default if s.temperature is None else round(s.temperature, 2) for s in config.scenarios]

    keys: list[str] = []
    for n, (s, t) in enumerate(zip(config.scenarios, temperatures), start=1):
        if s.network.jitter_ms and not s.network.delay_ms:
            raise ValueError(f"Scenario {n} has a jitter of {s.network.jitter_ms} ms and no delay. Jitter needs a delay.")
        # Captures are named by everything the scenario sets: <model>-t0.7-d500ms-j50ms-normal-pNN.pcap
        key = f"{model_dir_name(s.model)}-t{t:g}-{describe(s.network)[1]}"
        if key in keys:
            raise ValueError(f"Scenario {n} is the same as scenario {keys.index(key) + 1}.")
        keys.append(key)

    labels = _labels(config.scenarios, temperatures)
    for n, label in enumerate(labels, start=1):
        first = labels.index(label) + 1
        if first < n:
            raise ValueError(f"Scenarios {first} and {n} are both called {label}. Give them different labels.")

    return [
        Variant(
            key=key,
            label=label,
            model=s.model,
            temperature=t,
            network=s.network.model_dump() if s.network.delay_ms else None,
            columns={
                "scenario": label,
                "model": s.model,
                "temperature": t,
                "delay_ms": s.network.delay_ms,
                "jitter_ms": s.network.jitter_ms,
                "distribution": s.network.distribution if s.network.jitter_ms else None,
            },
        )
        for s, t, key, label in zip(config.scenarios, temperatures, keys, labels)
    ]


def prompts(config: CustomExperimentConfig) -> dict[int, dict]:
    """The run's prompts: from the prompt library, or the written ones (those given, or the saved ones)."""
    if config.prompt_source == "library":
        if config.prompt_texts is not None:
            raise ValueError('prompt_texts needs prompt_source "written". With "library", the prompts are '
                             "prompt library numbers in prompts.")
        return library_prompts(config)
    if config.prompts is not None:
        raise ValueError('With prompt_source "written", the prompts themselves go in prompt_texts, '
                         "not prompt library numbers in prompts.")
    return numbered(config.prompt_texts if config.prompt_texts is not None else saved_prompts(SAVED_FILE, default=[]))


KIND = Kind(
    slug="custom-experiment",
    title="Custom Experiment",
    config=CustomExperimentConfig,
    variants=variants,
    variable="Scenario",
    prompts=prompts,
)

# The written prompts being worked on, next to the experiment's runs. None until some are saved.
router = saved_prompts_router(KIND, SAVED_FILE, default=[])
