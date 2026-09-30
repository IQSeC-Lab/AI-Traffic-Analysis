"""
Experiment 3, ported from 3-Temperature-change: the same capture at several sampling
temperatures. The original baked one TEMPERATURE into inference_server.py and was
run once per value; here a run sweeps several, each passed to the server with
--temperature. 0 is greedy decoding (always the most likely token).
"""

from typing import Annotated

from pydantic import Field

from storage import model_dir_name

from .base import MAX_VARIANTS, Kind, ModelRef, RunConfig, Variant


class TemperatureChangeConfig(RunConfig):
    model: ModelRef
    temperatures: list[Annotated[float, Field(ge=0, le=2)]] = Field(
        [0.3, 0.7, 0.9],
        min_length=1,
        max_length=MAX_VARIANTS,
        description="Sampling temperatures to compare, 0 to 2 (0 is greedy decoding). "
                    "Every prompt is captured once at each.",
    )


def variants(config: TemperatureChangeConfig) -> list[Variant]:
    base = model_dir_name(config.model)
    found: list[Variant] = []
    for value in config.temperatures:
        t = round(value, 2)
        if any(v.temperature == t for v in found):
            raise ValueError(f"Temperature {t:g} is listed twice.")
        found.append(Variant(
            key=f"{base}-t{t:g}",
            label=f"Temperature {t:g}",
            model=config.model,
            temperature=t,
            columns={"temperature": t},
        ))
    return found


KIND = Kind(
    slug="temperature-change",
    title="Temperature Change",
    config=TemperatureChangeConfig,
    variants=variants,
    variable="Temperature",
)
