"""
Experiment 5, ported from 5-Scalability: the same prompts sent to several models, so
the model is the only thing that changes between their captures. The original ran
one model per invocation (uncommenting MODEL in main.py); a run here captures all
of them, and reserves GPU memory for the largest.
"""

from pydantic import Field

from storage import model_dir_name

from .base import MAX_VARIANTS, Kind, ModelRef, RunConfig, Variant


class ScalabilityConfig(RunConfig):
    models: list[ModelRef] = Field(
        ...,
        min_length=1,
        max_length=MAX_VARIANTS,
        description="Models to compare. Every prompt is captured once on each.",
    )


def variants(config: ScalabilityConfig) -> list[Variant]:
    found: list[Variant] = []
    for model in config.models:
        # Captures keep the names of 5-Scalability: <model>-pNN.pcap
        key = model_dir_name(model)
        if any(v.key == key for v in found):
            raise ValueError(f"{model} is listed twice.")
        found.append(Variant(key=key, label=model, model=model, columns={"model": model}))
    return found


KIND = Kind(
    slug="scalability",
    title="Scalability",
    config=ScalabilityConfig,
    variants=variants,
    variable="Model",
)
