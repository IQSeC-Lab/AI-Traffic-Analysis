# 3-Temperature Change

Variant of the data collector that runs the same traffic capture experiment at a **fixed, configurable temperature**. This allows you to measure how sampling temperature affects LLM network traffic patterns (token timing, packet sizes, inter-token gaps).

## Project Files

| File                    | Purpose                                                                   |
| ----------------------- | ------------------------------------------------------------------------- |
| `main.py`               | Orchestrator — same as 2-Data-collector                                  |
| `inference_server.py`   | FastAPI server with **hardcoded temperature** for streaming generation    |
| `client.py`             | SSE stream consumer with per-token timing (same as 2-Data-collector)     |
| `Dockerfile.llmtool`    | Builds the `llm-toolbox` Docker image                                     |

## Where to Change the Temperature

The temperature is set in **`inference_server.py`** at the top of the file:

```python
# ── Sampling temperature (change this between runs) ──────────────────────────
TEMPERATURE = 0.9
# ─────────────────────────────────────────────────────────────────────────────
```

Both the streaming endpoint (`/generate`) and the sync endpoint (`/generate/sync`) reference this single `TEMPERATURE` variable.

## How to Change the Temperature

1. Edit `TEMPERATURE` at the top of `inference_server.py`
2. Run `python3 main.py` — the Docker image is rebuilt automatically on each run, so the new value takes effect immediately

### Common Temperature Values

| Temperature | Behavior                                    |
| ----------- | ------------------------------------------- |
| `0.0`       | Greedy — always picks the most likely token |
| `0.3`       | Low diversity, near-deterministic            |
| `0.7`       | Balanced (default in most APIs)             |
| `0.9`       | Higher diversity, more creative              |
| `1.0`       | Maximum diversity (default `do_sample` limit) |
| `>1.0`      | Very high randomness, may produce incoherent text |

## Configuration

Edit the top of `main.py`:

| Variable         | Default                     | Description                        |
| ---------------- | --------------------------- | ---------------------------------- |
| `MODEL`          | `MegaScience/Qwen3-14B-MegaScience` | HuggingFace model ID        |
| `DOCKER_NETWORK` | `llm-net-temp`              | Isolated Docker bridge network     |
| `GPU_DEVICE`     | `device=0`                  | GPU device for Docker              |
| `MAX_TOKENS`     | `2048`                      | Max generated tokens               |

## Usage

```bash
# Run all 60 prompts at the configured temperature
python3 main.py

# Run a single prompt N times
python3 main.py --prompt 1 --repeat 100
```

## Typical Workflow for Temperature Comparison

1. Set `temperature=0.3` in `inference_server.py`, run `python3 main.py`
2. Set `temperature=0.7` in `inference_server.py`, run `python3 main.py`
3. Set `temperature=0.9` in `inference_server.py`, run `python3 main.py`
4. Compare the resulting PCAPs and timing data across runs

## Output

Same as 2-Data-collector:

```
captures/    # PCAP files per prompt
logs/        # Prompt text, model response, server logs, and per-token timing
models/      # Pre-downloaded model weights (read-only mount)
```

## Notes

- The temperature is **not** passed as a CLI argument or environment variable — it is baked into `inference_server.py` at the `generation_kwargs` dict. You must edit the source file directly.
- Each `main.py` invocation rebuilds the Docker image, so source edits take effect automatically.
- Network is `--internal` — no outbound internet. Model must be pre-downloaded.
