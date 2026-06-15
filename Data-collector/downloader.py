#!/usr/bin/env python3
"""
Pre-download a HuggingFace model to a local flat directory on the HOST.
Run this once before starting the experiment.

Usage:
    python downloader.py --model prithivMLmods/Evac-Opus-14B-Exp
    python downloader.py --model prithivMLmods/Evac-Opus-14B-Exp --output ./models
"""

import argparse
import sys
from pathlib import Path


def parse_args():
    ap = argparse.ArgumentParser(description="HuggingFace model downloader")
    ap.add_argument("--model",    required=True,         help="HF repo id, e.g. org/model-name")
    ap.add_argument("--output",   default="./models",    help="Root dir to store models (default: ./models)")
    ap.add_argument("--revision", default=None,          help="Branch / commit hash (default: main)") 
    # HERE YOU CAN ADD YOUR TOKEN OR JUST PASS IT AS A FLAG
    ap.add_argument("--token",    default="",          help="HF token (or set HF_TOKEN env var)")
    return ap.parse_args()


def model_dir(output_root: str, model_name: str) -> Path:
    safe = model_name.replace("/", "-").replace(":", "-")
    return Path(output_root) / safe


def already_downloaded(target: Path) -> bool:
    """
    A model directory is considered complete when it contains at least one
    .safetensors or .bin weight file AND a config.json.
    """
    if not target.exists():
        return False
    has_config  = (target / "config.json").exists()
    has_weights = (
        any(target.glob("*.safetensors")) or 
        any(target.glob("*.bin"))
    )
    return has_config and has_weights


def download(model_name: str, target: Path, revision: str, token: str):
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("[downloader] huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    target.mkdir(parents=True, exist_ok=True)
    print(f"[downloader] Downloading '{model_name}' → {target}")
    snapshot_download(
        repo_id=model_name,
        local_dir=str(target),
        local_dir_use_symlinks=False,   # flat copy — no symlink tree
        revision=revision,
        token=token,
        resume_download=True,           # safe to re-run if interrupted
        ignore_patterns=["*.msgpack", "*.h5", "flax_model*", "tf_model*"],  # skip non-PyTorch weights
    )
    print(f"[downloader] ✓ Download complete → {target}")


def main():
    args   = args_parsed = parse_args()
    import os
    token  = args.token or os.environ.get("HF_TOKEN") or None
    target = model_dir(args.output, args.model)

    print(f"[downloader] Model  : {args.model}")
    print(f"[downloader] Target : {target}")

    if already_downloaded(target):
        print(f"[downloader] ✓ Already downloaded — skipping. Delete '{target}' to force re-download.")
        sys.exit(0)

    download(args.model, target, args.revision, token)


if __name__ == "__main__":
    main()
