# 2-Data Collector

Orchestrates LLM inference traffic capture experiments within an isolated Docker network. For each prompt, it spins up a fresh inference container + a sidecar `tcpdump` container, sends the prompt via SSE streaming (mimicking ChatGPT), saves the PCAP and logs, then tears everything down.

## Project Files

| File                    | Purpose                                                                   |
| ----------------------- | ------------------------------------------------------------------------- |
| `main.py`               | Orchestrator — builds image, creates network, runs experiment, saves outputs |
| `inference_server.py`   | FastAPI server that loads a HuggingFace model and streams tokens via SSE  |
| `client.py`             | Connects to the inference server, sends a prompt, reads the SSE stream token-by-token, and records per-token timing |
| `r1.py`                 | Helper script to batch-run a range of prompts (100 repeats each)          |
| `Dockerfile.llmtool`    | Builds the `llm-toolbox` image (Python 3.10-slim + torch + transformers) |

## Prerequisites

- NVIDIA GPU with drivers
- Docker with GPU access (`nvidia-container-toolkit`)
- Python 3.10+ on the host
- `pip install huggingface_hub` on the host (for model downloading)
- HuggingFace token for gated models (set via `--token` flag or `HF_TOKEN` env var)

## Setup

**1. Download a model** (uses the script from `1-Model_downloader`):

```bash
python3 ../1-Model_downloader/downloader.py --model Qwen/Qwen2.5-7B-Instruct
```

Weights are saved to `./models/<model-name>/`.

**2. Run the experiment:**

```bash
python3 main.py
```

On first run, this builds the `llm-toolbox` Docker image and creates the isolated `llm-net1` internal bridge network.

## Configuration

Edit the top of `main.py`:

| Variable         | Default                    | Description                        |
| ---------------- | -------------------------- | ---------------------------------- |
| `MODEL`          | `Qwen/Qwen2.5-7B-Instruct` | HuggingFace model ID              |
| `DOCKER_NETWORK` | `llm-net1`                 | Isolated Docker bridge network     |
| `GPU_DEVICE`     | `device=0`                 | GPU device for Docker              |
| `MAX_TOKENS`     | `2048`                     | Max generated tokens               |
| `SERVER_TIMEOUT` | `900`                      | Inference server timeout (seconds) |

## Usage

### Run all 60 prompts once (default)

```bash
python3 main.py
```

### Run a single prompt N times

```bash
python3 main.py --prompt 1 --repeat 100
```

Each iteration gets a fresh container + PCAP.

### Batch-run a range of prompts

```bash
python3 r1.py
```

`r1.py` loops over a range of prompt indices (currently 31–60) and runs each 100 times. Edit the `range()` call in `r1.py` to change the prompt set.

## Prompt Categories

The 60 prompts in `main.py` cover:

| Category                     | Prompts | Source / Notes                                     |
| ---------------------------- | ------- | -------------------------------------------------- |
| Text Summarization           | 1–10    | Historical documents from MMLU high school history  |
| Code Generation              | 11–20   | Python questions from MMLU + custom                |
| Math / Algorithmic Reasoning | 21–30   | From LLMAP dataset                                 |
| Malware / Adversarial        | 31–40   | Adversarial prompts for safety testing             |
| Logical Reasoning & Puzzles  | 41–50   | Behavioral interview-style questions               |
| Technical Explanation        | 51–60   | Science/tech questions from MMLU                   |

## Output

Each run produces:

```
captures/    # PCAP files (all eth0 traffic per inference container)
logs/        # Prompt text, model response, and server logs
models/      # Pre-downloaded model weights (read-only mount)
```

## Notes

- Network is `--internal` — no outbound internet from containers. Model must be pre-downloaded on the host.
- Inference server runs with `local_files_only=True`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.
- Each prompt gets a **fresh container** — every conversation starts clean.
- PCAPs capture all eth0 traffic via a tcpdump sidecar sharing the inference container's network namespace.
- `client.py` records per-token timing data (`t`, `dt`, `text`) in the JSON output for latency analysis.
