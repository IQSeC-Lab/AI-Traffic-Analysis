"""Experiment 2, ported from 2-Data-Collector: the baseline capture of every prompt on one model."""

from storage import model_dir_name

from .base import Kind, ModelRef, RunConfig, Variant


class DataCollectorConfig(RunConfig):
    model: ModelRef = "Qwen/Qwen2.5-7B-Instruct"


def variants(config: DataCollectorConfig) -> list[Variant]:
    # Captures keep the names of 2-Data-Collector: <model>-pNN.pcap
    return [Variant(key=model_dir_name(config.model), label=config.model, model=config.model)]


KIND = Kind(slug="data-collector", title="Data Collector", config=DataCollectorConfig, variants=variants)
