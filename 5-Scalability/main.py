#!/usr/bin/env python3
"""
main.py
Orchestrates the full experiment:
  - Builds llm-toolbox Docker image
  - Creates isolated internal Docker network (llm-net)
  - Validates model is pre-downloaded on host
  - For each prompt:
      1. Starts a fresh inference container  (new conversation)
      2. Starts a sidecar tcpdump container  (captures only that container's traffic)
      3. Sends the prompt via a client container inside llm-net
      4. Saves PCAP + logs, tears everything down


Prerequisites:
    python3 downloader.py --model prithivMLmods/Evac-Opus-14B-Exp
    python3 main.py

"""

import os 
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
import argparse
import json
import subprocess
import textwrap
import time
from pathlib import Path


# =============================================================================
# Configuration
# =============================================================================

# ------------------------------------------------
# Text models only 
# MODEL = "HaolunLi/LLaMA-3.2-3B-SRL"
# MODEL = "Xtra-Computing/XtraGPT-3B"
# MODEL = "LaaLM/LaaLM-exp-v1"
# MODEL = "OpceanAI/Yuuki-NxG"


# MODEL = "unsloth/Phi-4-mini-reasoning"
# MODEL = "PatronusAI/glider"
# MODEL = "sail/Sailor-4B"
# MODEL = "Qwen/Qwen1.5-4B-Chat"

# MODEL = "nvidia/AceReason-Nemotron-1.1-7B"
# MODEL = "Qwen/Qwen2.5-7B-Instruct"
MODEL = "Intel/neural-chat-7b-v3-3"
# MODEL = "mistralai/Mistral-7B-Instruct-v0.2"

# MODEL = "typhoon-ai/llama3.1-typhoon2-8b-instruct"
# MODEL = "rfrancu/LLMTwin-Llama-3.1-8B"
# MODEL = "allenai/Llama-3.1-Tulu-3-8B"
# MODEL = "dphn/dolphin-2.9-llama3-8b"

# MODEL = "Qwen/Qwen3-14B-Base"
# MODEL = "MegaScience/Qwen3-14B-MegaScience"
# MODEL = "TeichAI/Qwen3-14B-Gemini-3-Pro-Preview-High-Reasoning-Distill"
# MODEL = "0xA50C1A1/Qwen3-14B-Heretic"

# ------------------------------------------------

DOCKER_NETWORK = "llm-net-sca-1"
GPU_DEVICE     = "device=0"
INFERENCE_PORT = 8000
MAX_TOKENS     = 2048
SERVER_TIMEOUT = 900


CAPTURES_DIR = Path("./captures")
LOGS_DIR     = Path("./logs")
MODELS_DIR   = Path("./models")


for d in (CAPTURES_DIR, LOGS_DIR, MODELS_DIR):
    d.mkdir(exist_ok=True)


CAPTURES_ABS = str(CAPTURES_DIR.resolve())
MODELS_ABS   = str(MODELS_DIR.resolve())
LOGS_ABS     = str(LOGS_DIR.resolve())


MODEL_SAFE           = MODEL.replace("/", "-").replace(":", "-")
MODEL_DIR_NAME       = MODEL_SAFE
MODEL_CONTAINER_PATH = f"/models/{MODEL_DIR_NAME}"


# =============================================================================
# Prompts
# =============================================================================



PROMPTS = [
    

    # Code Generation
    # Extracted from https://huggingface.co/datasets/cais/mmlu/viewer/high_school_computer_science?row=9 and some from me 
    # 1
    "Let x = 1. What is x << 3 in Python 3? write code to validate your answer and then proceed to answer.",
    # 2
    "In Python 3, what is the output of print tuple[0] if tuple = ( 'abcd', 786 , 2.23, 'john', 70.2 )? write python code to validate your answer ",
    # 3
    """
    Consider the following code segment, which uses the variables r, s, and t.
    r ← 1
    s ← 2
    t ← 3
    r ← s
    s ← t
    print(r)
    print(s)

    write code to validate your answer and then answer What is displayed as a result of running the code segment?
    """,
    # 4
    "Let a be a array of 500 strings that are unorganized, generate me code to sort the array using bubble sort.",
    # 5
    "Write a function in python to generate a list of numbers. The input is n, which is the number of random numbers to be generated and the output is the list with the numbers.",
    # 6
    "Write a function that returns True if a word is a palindrome and False otherwise.",
    # 7
    "write a function that finds the largest number in a list without using max()",
    # 8
    "Implement binary search in python",
    # 9
    "write a function that given a list of integers, it return how many times each number appears.",
    # 10
    "Write a function that returns the nth Fibonacci number.",

]






# =============================================================================
# Dockerfile + embedded scripts (written to disk, baked into image)
# =============================================================================


DOCKERFILE = """\
FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \\
      "huggingface_hub>=0.23.0" \\
      "transformers>=4.40.0" \\
      "torch" \\
      "accelerate" \\
      "fastapi" \\
      "uvicorn" \\
      "requests"
WORKDIR /app
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
ENV TOKENIZERS_PARALLELISM=false
COPY inference_server.py /app/inference_server.py
COPY client.py           /app/client.py
"""


# =============================================================================
# Utilities
# =============================================================================


def log(msg: str):
    print(msg, flush=True)



def run_cmd(cmd: str):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.stdout, p.stderr, p.returncode



def must(cmd: str, ctx: str):
    out, err, rc = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(
            f"{ctx} failed (rc={rc})\n"
            f"CMD : {cmd}\n"
            f"STDERR:\n{err}\n"
            f"STDOUT:\n{out}"
        )
    return out, err



def docker_rm(name: str):
    run_cmd(f"docker rm -f {name} >/dev/null 2>&1 || true")


# =============================================================================
# Setup
# =============================================================================


def ensure_image():
    log("[setup] Building llm-toolbox Docker image...")
    Path("Dockerfile.llmtool").write_text(DOCKERFILE)
    must("docker build -t llm-toolbox -f Dockerfile.llmtool .", "docker build llm-toolbox")
    run_cmd("docker pull nicolaka/netshoot >/dev/null 2>&1 || true")
    log("[setup] ✓ Images ready.")



def ensure_network():
    _, _, rc = run_cmd(f"docker network inspect {DOCKER_NETWORK} >/dev/null 2>&1")
    if rc != 0:
        must(
            f"docker network create --driver bridge --internal {DOCKER_NETWORK}",
            f"create network {DOCKER_NETWORK}",
        )
        log(f"[setup] ✓ Created isolated network: {DOCKER_NETWORK}")
    else:
        log(f"[setup] ✓ Network '{DOCKER_NETWORK}' already exists — reusing.")



def validate_model_dir():
    model_dir = MODELS_DIR / MODEL_DIR_NAME
    if not model_dir.exists():
        raise RuntimeError(
            f"[setup] Model directory not found: {model_dir}\n"
            f"       Run: python3 downloader.py --model {MODEL}"
        )
    has_weights = (
        any(model_dir.glob("*.safetensors")) or
        any(model_dir.glob("*.bin"))
    )
    if not has_weights:
        raise RuntimeError(
            f"[setup] Model directory has no weight files: {model_dir}\n"
            f"       Re-run: python3 downloader.py --model {MODEL}"
        )
    log(f"[setup] ✓ Model directory valid: {model_dir}")


# =============================================================================
# Per-prompt experiment
# =============================================================================


def start_inference() -> str:
    cname = f"llm-{MODEL_SAFE}"
    docker_rm(cname)
    cmd = (
        f"docker run -d --name {cname} "
        f"--network {DOCKER_NETWORK} "
        f"--gpus \"{GPU_DEVICE}\" "
        f"-v \"{MODELS_ABS}:/models:ro\" "
        f"-e HF_HUB_OFFLINE=1 "
        f"-e TRANSFORMERS_OFFLINE=1 "
        f"--shm-size 2g "
        f"llm-toolbox python /app/inference_server.py "
        f"--model-name \"{MODEL}\" "
        f"--model-path \"{MODEL_CONTAINER_PATH}\""
    )
    must(cmd, "start inference server")
    log(f"[inference] ✓ Container started: {cname}")
    return cname



def start_capture(inf_container: str, index: int) -> str:
    tc_cname  = f"tcpdump-{MODEL_SAFE}-p{index:02d}"
    pcap_file = f"/captures/{MODEL_SAFE}-p{index:02d}.pcap"
    docker_rm(tc_cname)
    time.sleep(2)
    cmd = (
        f"docker run -d --name {tc_cname} "
        f"--network container:{inf_container} "
        f"-v \"{CAPTURES_ABS}:/captures\" "
        f"--cap-add=NET_RAW --cap-add=NET_ADMIN "
        f"nicolaka/netshoot tcpdump -i eth0 -s0 -U -w {pcap_file}"
    )
    _, err, rc = run_cmd(cmd)
    if rc != 0:
        log(f"[capture] Failed to start sidecar: {err.strip()}")
        return tc_cname
    time.sleep(2)
    logs, _, _ = run_cmd(f"docker logs {tc_cname} 2>&1")
    if "listening on" in logs.lower():
        log(f"[capture] ✓ Sidecar active → {MODEL_SAFE}-p{index:02d}.pcap")
    else:
        log(f"[capture] ⚠ tcpdump status unclear: {logs[:200]}")
    return tc_cname



def stop_capture(tc_cname: str):
    run_cmd(f"docker stop {tc_cname} >/dev/null 2>&1 || true")
    time.sleep(1)
    docker_rm(tc_cname)



def send_prompt_via_client(inf_container: str, prompt: str, index: int) -> str | None:
    """
    Write the prompt to a file, mount it into a client container,
    reach the inference server by Docker container-name DNS inside llm-net.
    """
    cname       = f"client-{MODEL_SAFE}-p{index:02d}"
    prompt_file = LOGS_DIR / f"prompt_{index:02d}.txt"
    prompt_file.write_text(prompt)
    docker_rm(cname)


    cmd = (
        f"docker run --rm --name {cname} "
        f"--network {DOCKER_NETWORK} "
        f"-v \"{LOGS_ABS}:/prompts:ro\" "
        f"llm-toolbox python /app/client.py "
        f"--host {inf_container} "
        f"--port {INFERENCE_PORT} "
        f"--index {index} "
        f"--max-tokens {MAX_TOKENS} "
        f"--prompt-file /prompts/prompt_{index:02d}.txt"
    )
    log(f"[client] Sending prompt #{index}...")
    out, err, rc = run_cmd(cmd)
    if rc != 0:
        log(f"[client] Error on prompt #{index}: {err.strip()[:300]}")
        return None
    try:
        # Last JSON line is the result printed by client.py
        last_json_line = [l for l in out.strip().splitlines() if l.startswith("{")][-1]
        result = json.loads(last_json_line)
        log(f"[client] ✓ Prompt #{index} response received")
        return result.get("response")
    except Exception:
        log(f"[client] Could not parse client output: {out[:300]}")
        return None



def collect_logs(inf_container: str, index: int,
                 prompt: str = None, response: str = None):
    safe     = f"{MODEL_SAFE}-p{index:02d}"
    out, err, rc = run_cmd(f"docker logs {inf_container}")
    log_path = LOGS_DIR / f"{safe}.log"
    with log_path.open("w") as f:
        f.write("=" * 60 + "\n")
        f.write(f"PROMPT #{index}\n")
        f.write("=" * 60 + "\n")
        f.write(f"INPUT:\n{prompt or 'N/A'}\n\n")
        f.write(f"OUTPUT:\n{response or 'N/A'}\n")
        f.write("=" * 60 + "\n")
        f.write("SERVER LOGS:\n")
        f.write("=" * 60 + "\n")
        f.write(out if rc == 0 else f"(log collection failed: {err.strip()})")
    log(f"[logs] Saved → {log_path}")



def run_experiment_for_prompt(prompt: str, index: int):
    log("=" * 60)
    log(f"Prompt #{index:02d} / {len(PROMPTS)}  —  {MODEL}")
    log("=" * 60)


    inf_container = None
    tc_cname      = None
    response      = None


    try:
        inf_container = start_inference()
        tc_cname      = start_capture(inf_container, index)
        response      = send_prompt_via_client(inf_container, prompt, index)
        time.sleep(5)   # let tcpdump flush remaining packets


    except Exception as e:
        log(f"[experiment] ERROR on prompt #{index}: {e}")
        import traceback
        traceback.print_exc()


    finally:
        if inf_container:
            collect_logs(inf_container, index, prompt=prompt, response=response)
            docker_rm(inf_container)
        if tc_cname:
            stop_capture(tc_cname)


        pcap = CAPTURES_DIR / f"{MODEL_SAFE}-p{index:02d}.pcap"
        if pcap.exists():
            size_mb = pcap.stat().st_size / 1024 / 1024
            log(f"[capture] ✓ PCAP → {pcap} ({size_mb:.2f} MB)")
        else:
            log(f"[capture] ⚠ PCAP not found for prompt #{index}")


# =============================================================================
# Repeated prompt experiment (new functionality)
# =============================================================================


def run_repeated_prompt(prompt_index: int, repeat_count: int):
    """
    Run the same prompt multiple times (e.g., 100 times).
    Each iteration gets a fresh inference container and capture.
    """
    if prompt_index < 1 or prompt_index > len(PROMPTS):
        raise ValueError(f"Invalid prompt index {prompt_index}. Must be between 1 and {len(PROMPTS)}.")

    prompt = PROMPTS[prompt_index - 1]

    log("=" * 60)
    log(f"REPEATED PROMPT MODE")
    log(f"Prompt  : #{prompt_index:02d}")
    log(f"Repeats : {repeat_count}")
    log(f"Model   : {MODEL}")
    log("=" * 60)

    for iteration in range(1, repeat_count + 1):
        log("")
        log("-" * 60)
        log(f"Iteration {iteration} / {repeat_count}")
        log("-" * 60)

        # Use a composite index: prompt number + iteration
        composite_index = prompt_index * 1000 + iteration

        inf_container = None
        tc_cname      = None
        response      = None

        try:
            inf_container = start_inference()
            tc_cname      = start_capture(inf_container, composite_index)
            response      = send_prompt_via_client(inf_container, prompt, composite_index)
            time.sleep(5)
        except Exception as e:
            log(f"[experiment] ERROR on iteration {iteration}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if inf_container:
                collect_logs(inf_container, composite_index, prompt=prompt, response=response)
                docker_rm(inf_container)
            if tc_cname:
                stop_capture(tc_cname)

            pcap = CAPTURES_DIR / f"{MODEL_SAFE}-p{composite_index:02d}.pcap"
            if pcap.exists():
                size_mb = pcap.stat().st_size / 1024 / 1024
                log(f"[capture] ✓ PCAP → {pcap} ({size_mb:.2f} MB)")
            else:
                log(f"[capture] ⚠ PCAP not found for iteration {iteration}")

    log("")
    log("=" * 60)
    log(f"✓ Completed {repeat_count} iterations of prompt #{prompt_index:02d}")
    log("=" * 60)


# =============================================================================
# Entry point
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="LLM Traffic Capture — Isolated Docker Network",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 main.py                    # Run all prompts once (default)
  python3 main.py -p 1 -r 100        # Send prompt #1, 100 times
  python3 main.py --prompt 5 --repeat 50   # Send prompt #5, 50 times
        """
    )
    parser.add_argument(
        "-p", "--prompt",
        type=int,
        default=None,
        help="Prompt index to send repeatedly (1-based). If omitted, runs all prompts once."
    )
    parser.add_argument(
        "-r", "--repeat",
        type=int,
        default=100,
        help="Number of times to repeat the selected prompt (default: 100)."
    )
    args = parser.parse_args()

    log("=" * 60)
    log("LLM Traffic Capture — Isolated Docker Network")
    log(f"Model   : {MODEL}")
    log(f"Network : {DOCKER_NETWORK}  (--internal bridge, no internet routing)")
    log(f"GPU     : {GPU_DEVICE}")
    log("=" * 60)

    ensure_image()
    ensure_network()
    validate_model_dir()

    if args.prompt is not None:
        # Repeated prompt mode
        run_repeated_prompt(args.prompt, args.repeat)
    else:
        # Default mode: all prompts once
        log(f"Prompts : {len(PROMPTS)}")
        for i, prompt in enumerate(PROMPTS, start=1):
            run_experiment_for_prompt(prompt, i)

    log("=" * 60)
    log("✓ Experiment complete!")
    log("=" * 60)



if __name__ == "__main__":
    main()
