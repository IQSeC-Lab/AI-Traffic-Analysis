#!/usr/bin/env python3
import subprocess
import time
import json
import textwrap
from pathlib import Path
import urllib.request

# =========================
# Configuration
# =========================
RUN_DURATION_MINUTES = 30

# MODEL = "Ramikan-BR/Qwen2-0.5B-v14"
MODEL = "cobrokerai/llama-3-1-8b"


PROMPTS = [
    "What is machine learning?",
    "Explain neural networks.",
    "What are the applications of AI?",
    "Describe deep learning architectures.",
    "What is natural language processing?",
]

# Directory setup
CAPTURES_DIR = Path("./captures")
LOGS_DIR = Path("./logs")
MODELS_DIR = Path("./models")

for d in (CAPTURES_DIR, LOGS_DIR, MODELS_DIR):
    d.mkdir(exist_ok=True)

CAPTURES_HOST_ABS = str(CAPTURES_DIR.resolve())
MODELS_HOST_ABS = str(MODELS_DIR.resolve())

def log(msg: str):
    print(msg, flush=True)

def run_cmd(cmd: str):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.stdout, p.stderr, p.returncode

def must(cmd: str, ctx: str):
    out, err, rc = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"{ctx} failed (rc={rc}).\ncmd={cmd}\nSTDERR:\n{err}\nSTDOUT:\n{out}")
    return out, err

def docker_rm(name: str):
    run_cmd(f"docker rm -f {name} >/dev/null 2>&1 || true")

def model_to_safe_name(model_name: str) -> str:
    return model_name.replace("/", "-").replace(":", "-")

# -------------------------
# Embedded container scripts
# -------------------------
DOWNLOADER_PY = r"""
import os, argparse
from huggingface_hub import snapshot_download

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--revision", default=None)
    args = ap.parse_args()

    token = os.environ.get("HF_TOKEN") or None
    cache_dir = os.environ.get("HF_HOME", "/data/hf")

    snapshot_download(repo_id=args.model, revision=args.revision, token=token, cache_dir=cache_dir)
    print("download_ok")

if __name__ == "__main__":
    main()
"""

INFERENCE_SERVER_PY = r"""
import os, argparse
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
import uvicorn

app = FastAPI()

class PromptRequest(BaseModel):
    prompt: str
    max_tokens: int = 150

MODEL_NAME = None
generator = None
tokenizer = None

@app.get("/health")
async def health():
    return {"status": "healthy", "model": MODEL_NAME}

@app.post("/generate")
async def generate_text(req: PromptRequest):
    out = generator(
        req.prompt,
        max_new_tokens=req.max_tokens,
        do_sample=True,
        temperature=0.7,
        pad_token_id=tokenizer.eos_token_id,
    )
    return {"response": out[0]["generated_text"]}

def load_model(model_name: str):
    global generator, tokenizer, MODEL_NAME
    MODEL_NAME = model_name

    tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        device_map="auto",
        torch_dtype="auto",
        low_cpu_mem_usage=True,
        local_files_only=True,
    )
    generator = pipeline("text-generation", model=model, tokenizer=tokenizer)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    load_model(args.model)
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
"""

def ensure_image():
    log("Setting up Docker images...")
    Path("downloader.py").write_text(textwrap.dedent(DOWNLOADER_PY).lstrip())
    Path("inference_server.py").write_text(textwrap.dedent(INFERENCE_SERVER_PY).lstrip())

    dockerfile = r"""
FROM python:3.10-slim
RUN pip install --no-cache-dir \
      "huggingface_hub>=0.20.0" \
      "transformers>=4.40.0" \
      "torch" \
      "accelerate" \
      "fastapi" \
      "uvicorn" \
      "requests"
WORKDIR /app
ENV HF_HOME=/data/hf
ENV TRANSFORMERS_CACHE=/data/hf
ENV HUGGINGFACE_HUB_CACHE=/data/hf
ENV TOKENIZERS_PARALLELISM=false
COPY downloader.py /app/downloader.py
COPY inference_server.py /app/inference_server.py
"""
    Path("Dockerfile.llmtool").write_text(textwrap.dedent(dockerfile).lstrip())
    must("docker build -t llm-toolbox -f Dockerfile.llmtool .", "docker build llm-toolbox")
    run_cmd("docker pull nicolaka/netshoot >/dev/null 2>&1 || true")
    log("Docker images ready.")

def download_model(model_name: str):
    safe = model_to_safe_name(model_name)
    cname = f"dl-{safe}"
    docker_rm(cname)

    cmd = f'''docker run --name {cname} --rm \
      -v "{MODELS_HOST_ABS}:/data/hf" \
      -e HF_TOKEN="${{HF_TOKEN:-}}" \
      llm-toolbox python /app/downloader.py --model "{model_name}"'''

    log(f"[{safe}] Downloading model...")
    out, err = must(cmd, f"[{safe}] download")

    if "download_ok" in out:
        log(f"[{safe}] Download complete ✓")
    else:
        log(f"[{safe}] Download completed but verification unclear")

def start_inference(model_name: str):
    safe = model_to_safe_name(model_name)
    cname = f"llm-{safe}"
    docker_rm(cname)
    port = 8000

    cmd = f'''docker run -d --name {cname} \
      -p {port}:8000 \
      -v "{MODELS_HOST_ABS}:/data/hf" \
      -e HF_HOME="/data/hf" \
      -e TRANSFORMERS_CACHE="/data/hf" \
      -e HUGGINGFACE_HUB_CACHE="/data/hf" \
      -e HF_HUB_OFFLINE="1" \
      -e TRANSFORMERS_OFFLINE="1" \
      --shm-size 2g \
      llm-toolbox python /app/inference_server.py --model "{model_name}"'''

    log(f"[{safe}] Starting inference server on port {port}...")
    must(cmd, f"[{safe}] start inference")
    return cname, port

def start_capture(inference_container: str, model_name: str):
    safe = model_to_safe_name(model_name)
    tcpdump_container = f"tcpdump-{safe}"
    pcap_file = f"/captures/{safe}.pcap"
    docker_rm(tcpdump_container)

    time.sleep(3)

    cmd = f'''docker run -d --name {tcpdump_container} \
      --net=container:{inference_container} \
      -v "{CAPTURES_HOST_ABS}:/captures" \
      --cap-add=NET_RAW --cap-add=NET_ADMIN \
      nicolaka/netshoot tcpdump -i any -s0 -U -w {pcap_file}'''

    out, err, rc = run_cmd(cmd)
    if rc != 0:
        log(f"[{safe}] ❌ Capture failed to start: {err.strip()}")
        return False

    time.sleep(2)
    check_logs, _, _ = run_cmd(f"docker logs {tcpdump_container} 2>&1")
    if "listening on" in check_logs.lower():
        log(f"[{safe}] ✓ Packet capture active -> {safe}.pcap")
        return True
    else:
        log(f"[{safe}] ⚠ tcpdump status unclear. Logs: {check_logs[:200]}")
        return False

def stop_capture(model_name: str):
    safe = model_to_safe_name(model_name)
    tcpdump_container = f"tcpdump-{safe}"
    log(f"[{safe}] Stopping capture...")
    run_cmd(f"docker stop {tcpdump_container} >/dev/null 2>&1 || true")
    time.sleep(1)
    docker_rm(tcpdump_container)

def wait_ready(port: int, model_name: str, timeout: int = 900):
    safe = model_to_safe_name(model_name)
    log(f"[{safe}] Waiting for server to be ready (timeout: {timeout}s)...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=5) as r:
                if r.status == 200:
                    log(f"[{safe}] ✓ Server ready")
                    return True
        except Exception:
            pass
        time.sleep(5)

    log(f"[{safe}] ❌ Timeout waiting for server")
    return False

def run_workload(port: int, model_name: str, minutes: float):
    safe = model_to_safe_name(model_name)
    end = time.time() + minutes * 60
    n = 0
    log(f"[{safe}] Starting {minutes} minute workload...")

    while time.time() < end:
        for prompt in PROMPTS:
            if time.time() >= end:
                break
            try:
                data = json.dumps({"prompt": prompt, "max_tokens": 30}).encode("utf-8")
                req = urllib.request.Request(
                    f"http://localhost:{port}/generate",
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=180) as r:
                    _ = r.read()
                n += 1
                if n % 5 == 0:
                    log(f"[{safe}] Completed {n} requests...")
                time.sleep(2)
            except Exception as e:
                log(f"[{safe}] Request error: {e}")
                time.sleep(3)

    log(f"[{safe}] ✓ Workload complete: {n} requests")

def collect_logs(inference_container: str, model_name: str):
    safe = model_to_safe_name(model_name)
    out, err, rc = run_cmd(f"docker logs {inference_container}")
    if rc == 0:
        p = LOGS_DIR / f"{safe}.log"
        p.write_text(out)
        log(f"[{safe}] Server logs saved -> {p}")
    else:
        log(f"[{safe}] Failed to collect logs: {err.strip()}")

def run_experiment():
    safe = model_to_safe_name(MODEL)
    inf_container = None

    try:
        # Step 1: Download
        download_model(MODEL)

        # Step 2: Start inference
        inf_container, port = start_inference(MODEL)

        # Step 3: Start capture
        time.sleep(5)
        capture_started = start_capture(inf_container, MODEL)

        # Step 4: Wait for ready
        if not wait_ready(port, MODEL):
            log(f"[{safe}] Aborting - server never became ready")
            return

        # Step 5: Run workload
        run_workload(port, MODEL, RUN_DURATION_MINUTES)

    except Exception as e:
        log(f"[{safe}] ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        if inf_container:
            stop_capture(MODEL)
            collect_logs(inf_container, MODEL)
            docker_rm(inf_container)

        # Verify PCAP
        pcap = CAPTURES_DIR / f"{safe}.pcap"
        if pcap.exists():
            size_mb = pcap.stat().st_size / 1024 / 1024
            log(f"[{safe}] ✓ PCAP created -> {pcap} ({size_mb:.2f} MB)")
        else:
            log(f"[{safe}] ⚠ WARNING: PCAP file not found")

if __name__ == "__main__":
    log("=" * 60)
    log("LLM Network Traffic Capture - Single Model Mode")
    log("=" * 60)
    log(f"Model: {MODEL}")
    log(f"Duration: {RUN_DURATION_MINUTES} minutes")
    log("=" * 60)

    ensure_image()
    run_experiment()

    log("=" * 60)
    log("Experiment complete!")
    log("=" * 60)
