"""
Experiment 2, ported from 2-Data-Collector: the baseline capture of every prompt on one model.

The model is served by the app's own server (a HuggingFace model loaded with transformers,
as in the original) or, with the Ollama provider, by Ollama (ollama_engine.py). The prompts,
the network and the capture are the same either way.
"""

import re
from typing import Literal

from pydantic import Field, model_validator

from settings import ollama_models
from storage import MODEL_REF_PATTERN, model_dir_name

from .base import Kind, RunConfig, Variant


class DataCollectorConfig(RunConfig):
    provider: Literal["transformers", "ollama"] = Field(
        "transformers",
        description="What serves the model: the app's own server (HuggingFace models) or Ollama (Ollama models).",
    )
    model: str = Field(
        "Qwen/Qwen2.5-7B-Instruct",
        description="With transformers: a HuggingFace model id, or a folder name in the models directory. "
                    "With ollama: a model of the Ollama library, e.g. llama3.2:3b. Must be downloaded.",
    )

    @model_validator(mode="after")
    def _model_of_the_provider(self):
        pattern = ollama_models.MODEL_PATTERN if self.provider == "ollama" else MODEL_REF_PATTERN
        if not re.fullmatch(pattern, self.model):
            raise ValueError(f"Not a model name for {self.provider}: {self.model}")
        return self


def variants(config: DataCollectorConfig) -> list[Variant]:
    # Captures keep the names of 2-Data-Collector: <model>-pNN.pcap
    columns = {"provider": config.provider} if config.provider == "ollama" else {}
    return [Variant(key=model_dir_name(config.model), label=config.model, model=config.model, columns=columns)]


def check(config: DataCollectorConfig, variants: list[Variant]) -> int:
    if config.provider == "ollama":
        return ollama_models.reserve_mb(config.model, on_gpu=config.gpus != [])
    from .engine import downloaded_models_mb   # the engine imports the kinds
    return downloaded_models_mb(config, variants)


def _runner(config: DataCollectorConfig):
    if config.provider != "ollama":
        return None
    from .ollama_engine import OllamaExperiment
    return OllamaExperiment


KIND = Kind(slug="data-collector", title="Data Collector", config=DataCollectorConfig, variants=variants,
            check=check, runner=_runner)
