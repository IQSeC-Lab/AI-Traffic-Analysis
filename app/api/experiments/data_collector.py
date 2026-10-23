"""
Experiment 2, ported from 2-Data-Collector: the baseline capture of every prompt on one model.

The model is served by the app's own server (a HuggingFace model loaded with transformers,
as in the original) or, with the Ollama provider, by Ollama (ollama_engine.py). The prompts,
the network and the capture are the same either way.
"""

from storage import model_dir_name

from .base import Kind, ModelRef, ProviderConfig, Variant


class DataCollectorConfig(ProviderConfig):
    model: ModelRef = "Qwen/Qwen2.5-7B-Instruct"


def variants(config: DataCollectorConfig) -> list[Variant]:
    # Captures keep the names of 2-Data-Collector: <model>-pNN.pcap
    return [Variant(key=model_dir_name(config.model), label=config.model, model=config.model)]


KIND = Kind(slug="data-collector", title="Data Collector", config=DataCollectorConfig, variants=variants)
