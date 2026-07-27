# 1-Model Downloader

Scripts to download LLM models from HuggingFace to a local flat directory.

## Prerequisites

```bash
pip install huggingface_hub
```

## Usage

### Download a single model

```bash
python downloader.py --model Qwen/Qwen2.5-7B-Instruct
```

Output goes to `./models/Qwen-Qwen2.5-7B-Instruct/` by default.

### Download to a custom directory

```bash
python downloader.py --model Qwen/Qwen2.5-7B-Instruct --output /path/to/models
```

### Download a specific revision (branch/commit)

```bash
python downloader.py --model Qwen/Qwen2.5-7B-Instruct --revision v1.0
```

### Authentication (gated models)

```bash
# Via flag
python downloader.py --model meta-llama/Llama-3.1-8B --token hf_YOUR_TOKEN

# Via environment variable
export HF_TOKEN=hf_YOUR_TOKEN
python downloader.py --model meta-llama/Llama-3.1-8B
```

### Download all models at once

```bash
bash downloader.sh
```

This downloads every model listed in `downloader.sh`. To add or remove models, edit the `MODELS_7B` or `MODELS_14B` arrays in that file.

## How it works

- Uses `huggingface_hub.snapshot_download()` with flat copies (no symlinks).
- Skips non-PyTorch files (`.msgpack`, `.h5`, flax/tf weights).
- Skips re-download if the target directory already has `config.json` + weight files.
- Safe to re-run — resumes interrupted downloads automatically.
