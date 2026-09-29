"""
Where the backend keeps files on the host. Shared by every feature.

    MALLM_MODELS_DIR  downloaded HuggingFace models   (default: <app>/models)
    MALLM_DATA_DIR    experiment outputs              (default: <app>/data)
"""

import os
from pathlib import Path

APP_ROOT   = Path(__file__).resolve().parents[1]
MODELS_DIR = Path(os.environ.get("MALLM_MODELS_DIR", APP_ROOT / "models")).resolve()
DATA_DIR   = Path(os.environ.get("MALLM_DATA_DIR", APP_ROOT / "data")).resolve()

# HuggingFace repo id, e.g. "Qwen/Qwen2.5-7B-Instruct"
MODEL_ID_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
# A repo id or a folder name in MODELS_DIR (models fetched with the CLI downloader have no repo id on record)
MODEL_REF_PATTERN = r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)?$"


def model_dir_name(model: str) -> str:
    """Flat folder name for a model, e.g. Qwen/Qwen2.5-7B-Instruct -> Qwen-Qwen2.5-7B-Instruct."""
    return model.replace("/", "-").replace(":", "-")


def has_weights(path: Path) -> bool:
    return any(path.glob("*.safetensors")) or any(path.glob("*.bin"))


def weights_bytes(path: Path) -> int:
    files = list(path.glob("*.safetensors")) or list(path.glob("*.bin"))
    return sum(f.stat().st_size for f in files)


def estimate_gpu_memory_mb(path: Path) -> int:
    """Rough GPU memory to load a model and generate: its weights (+15%) plus 1.5 GB
    for activations and the KV cache. Conservative for fp32 .bin checkpoints."""
    return int(weights_bytes(path) / 2**20 * 1.15 + 1536)
