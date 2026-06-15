# Data Collector

Orchestrates LLM inference traffic capture experiments within an isolated Docker network. For each prompt, it spins up a fresh inference container + a sidecar `tcpdump` container, sends the prompt via SSE streaming (mimicking ChatGPT), saves the PCAP and logs, then tears everything down.

<!-- ## Project Files

| File                  | Purpose                                                                      |
| --------------------- | ---------------------------------------------------------------------------- |
| `main.py`             | Orchestrator — builds image, creates network, runs experiment, saves outputs |
| `inference_server.py` | FastAPI server for llm                                                       |
| `client.py`           | sends prompts to the server                                                  |
| `downloader.py`       | Downloads a single HF model to `./models/<safe-name>/`                       |
| `downloader.sh`       | Batch-downloads multiple models sequentially                                 |
| `Dockerfile.llmtool`  | Builds `llm-toolbox` image (Python 3.10-slim + torch + transformers)         | -->

## Prerequisites

- NVIDIA GPU with drivers
- Docker with access to gpu
- Python 3.10+ (for `downloader.py` on host; containers use `python:3.10-slim`)
- `pip install huggingface_hub` on the host (for `downloader.py`)
- HuggingFace token (some models are gated; set via `--token` flag or `HF_TOKEN` env var)

## Setup

**1. Download a model:**

```bash
# Single model
python3 downloader.py --model Qwen/Qwen3-14B-Base

# With HF token (for faster downloads)
python3 downloader.py --model meta-llama/Llama-3.1-8B --token hf_...

# Batch download all models
bash downloader.sh
```

Weights are saved to `./models/<model-name>/`.

**2. Run the experiment:**

```bash
python3 main.py
```

On first run, it builds the `llm-toolbox` Docker image and creates the isolated `llm-net` internal bridge network.

## Configuration

Edit the top of `main.py`:

| Variable         | Default               | Description                        |
| ---------------- | --------------------- | ---------------------------------- |
| `MODEL`          | `Qwen/Qwen3-14B-Base` | HuggingFace model ID               |
| `GPU_DEVICE`     | `device=0`            | GPU device for Docker              |
| `MAX_TOKENS`     | `2048`                | Max generated tokens               |
| `SERVER_TIMEOUT` | `900`                 | Inference server timeout (seconds) |

## Usage

### Run all prompts once (default)

```bash
python3 main.py
```

### Run a single prompt N times

```bash
python3 main.py --prompt 1 --repeat 100
```

Each iteration gets a fresh container + PCAP.

### Alternate Use

This will execute `main.py` but every prompt is going to be executed 100 times. Make sure to change the name of your enviroment

```bash
sh runner.sh
```

## Notes

- Network is `--internal` — no outbound internet from containers. Model must be downloaded to host beforehand.
- Inference server runs with `local_files_only=True`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.
- Each prompt gets a **fresh container** — every conversation starts clean.
- PCAPs capture all eth0 traffic via a tcpdump sidecar sharing the inference container's network namespace.
