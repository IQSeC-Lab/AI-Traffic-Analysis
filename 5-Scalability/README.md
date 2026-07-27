# 5-Scalability

Tests how well LLM traffic fingerprints **scale across models**. The same set of prompts is sent to multiple models of different sizes and architectures, producing PCAP + timing data for each. By comparing traffic patterns across models, you can study whether fingerprinting techniques generalize or are model-specific.

## Project Files

| File                    | Purpose                                                                   |
| ----------------------- | ------------------------------------------------------------------------- |
| `main.py`               | Orchestrator — lists all target models, sends prompts, captures traffic   |
| `inference_server.py`   | FastAPI streaming server (temperature 0.7)                               |
| `client.py`             | SSE stream consumer with per-token timing                                |
| `r1.py`                 | Batch runner — sends prompts 1–10, 10 repeats each                       |
| `Dockerfile.llmtool`    | Builds the `llm-toolbox` Docker image                                     |

## Models Under Test

The following models are defined in `main.py`. Uncomment one at a time to test:

| Size Tier | Models                                                                    |
| --------- | ------------------------------------------------------------------------- |
| **~3B**   | `HaolunLi/LLaMA-3.2-3B-SRL`, `Xtra-Computing/XtraGPT-3B`, `LaaLM/LaaLM-exp-v1`, `OpceanAI/Yuuki-NxG` |
| **~4B**   | `unsloth/Phi-4-mini-reasoning`, `PatronusAI/glider`, `sail/Sailor-4B`, `Qwen/Qwen1.5-4B-Chat` |
| **~7B**   | `nvidia/AceReason-Nemotron-1.1-7B`, `Qwen/Qwen2.5-7B-Instruct`, `Intel/neural-chat-7b-v3-3`, `mistralai/Mistral-7B-Instruct-v0.2` |
| **~8B**   | `typhoon-ai/llama3.1-typhoon2-8b-instruct`, `rfrancu/LLMTwin-Llama-3.1-8B`, `allenai/Llama-3.1-Tulu-3-8B`, `dphn/dolphin-2.9-llama3-8b` |
| **~14B**  | `Qwen/Qwen3-14B-Base`, `MegaScience/Qwen3-14B-MegaScience`, `TeichAI/Qwen3-14B-Gemini-3-Pro-Preview-High-Reasoning-Distill`, `0xA50C1A1/Qwen3-14B-Heretic` |

## Prompts

10 code generation prompts (consistent across all models):

| #   | Prompt                                                    |
| --- | --------------------------------------------------------- |
| 1   | Python bit-shift with validation                          |
| 2   | Python tuple indexing with validation                      |
| 3   | Variable assignment tracing                                |
| 4   | Bubble sort implementation                                 |
| 5   | Random number list generator                               |
| 6   | Palindrome checker                                         |
| 7   | Find largest without `max()`                               |
| 8   | Binary search implementation                               |
| 9   | Frequency counter for integers                             |
| 10  | Nth Fibonacci number                                       |

Using the same prompts across models is critical — it isolates the model as the only variable, so any traffic differences are attributable to the model itself.

## Prerequisites

- NVIDIA GPU with drivers
- Docker with GPU access (`nvidia-container-toolkit`)
- Python 3.10+ on the host
- **All target models pre-downloaded** via `1-Model_downloader`:

```bash
python3 ../1-Model_downloader/downloader.py --model HaolunLi/LLaMA-3.2-3B-SRL
python3 ../1-Model_downloader/downloader.py --model Qwen/Qwen2.5-7B-Instruct
python3 ../1-Model_downloader/downloader.py --model Intel/neural-chat-7b-v3-3
# ... etc
```

## Setup

```bash
python3 main.py
```

Builds the `llm-toolbox` Docker image and creates the `llm-net-sca-1` isolated network on first run.

## Configuration

Edit the top of `main.py`:

| Variable         | Default                          | Description                        |
| ---------------- | -------------------------------- | ---------------------------------- |
| `MODEL`          | `Intel/neural-chat-7b-v3-3`     | HuggingFace model ID (uncomment one) |
| `DOCKER_NETWORK` | `llm-net-sca-1`                 | Isolated Docker bridge network     |
| `GPU_DEVICE`     | `device=0`                      | GPU device for Docker              |
| `MAX_TOKENS`     | `2048`                           | Max generated tokens               |

## Usage

### Run all 10 prompts for the active model

```bash
python3 main.py
```

### Run a single prompt N times

```bash
python3 main.py --prompt 1 --repeat 50
```

### Batch-run all prompts with repeats

```bash
python3 r1.py
```

Sends each of the 10 prompts 10 times (configurable via `REPEATS` in `r1.py`).

## Workflow for Cross-Model Comparison

For each model:

1. Uncomment the desired `MODEL` in `main.py`
2. Ensure the model is downloaded: `python3 ../1-Model_downloader/downloader.py --model <MODEL>`
3. Run: `python3 main.py` or `python3 r1.py`
4. Save the resulting `captures/` and `logs/` with the model name
5. Repeat for the next model

Example:

```bash
# Rename output dirs between runs to avoid overwriting
python3 main.py
mv captures captures-intel-neural-chat
mv logs logs-intel-neural-chat

# Switch model in main.py, then:
python3 main.py
mv captures captures-qwen25-7b
mv logs logs-qwen25-7b
```

## Output

```
captures/    # PCAP files per prompt (all eth0 traffic)
logs/        # Prompt text, model response, server logs, per-token timing
models/      # Pre-downloaded model weights (read-only mount)
```

## What to Compare Across Models

| Metric                        | What to Look For                                       |
| ----------------------------- | ------------------------------------------------------ |
| **Inter-token timing**        | Do different models have distinct `dt` distributions?  |
| **Packet sizes**              | Are token SSE frames different sizes across models?    |
| **TTFT (time to first token)** | Does model size correlate with first-token latency?   |
| **Total stream duration**     | How does generation speed scale with model size?       |
| **Fingerprint uniqueness**    | Can you classify which model produced a given PCAP?    |

## Notes

- Network is `--internal` — no outbound internet. All models must be pre-downloaded.
- Each prompt gets a **fresh container** — no conversation state carries over.
- Temperature is `0.7` across all models for fair comparison.
- `r1.py` uses 10 repeats to balance coverage with runtime across many models.
- The model list is organized by size tier — pick one model per tier for a representative comparison, or test all for maximum coverage.
