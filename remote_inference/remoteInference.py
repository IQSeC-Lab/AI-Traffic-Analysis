#!/usr/bin/env python3
import subprocess
import time
import textwrap
import os
from pathlib import Path

# =========================
# Configuration
# =========================
RUN_DURATION_MINUTES = .5
MODEL = "meta-llama/Llama-3.1-8B-Instruct"
HF_TOKEN = ""

PROMPTS = [
    "What is machine learning?",
    "Explain neural networks.",
    "What are the applications of AI?",
    "Describe deep learning architectures.",
    "What is natural language processing?",
]

CAPTURES_DIR = Path("./captures")
LOGS_DIR = Path("./logs")

for d in (CAPTURES_DIR, LOGS_DIR):
    d.mkdir(exist_ok=True)

CAPTURES_HOST_ABS = str(CAPTURES_DIR.resolve())

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
# Embedded Python script for remote inference
# -------------------------
REMOTE_INFERENCE_PY = r"""
import os
import time
from huggingface_hub import InferenceClient

# Configuration from environment
RUN_DURATION_MINUTES = float(os.environ.get("RUN_DURATION_MINUTES", "30"))
MODEL = os.environ.get("MODEL", "meta-llama/Llama-3.1-8B-Instruct")
HF_TOKEN = os.environ.get("HF_TOKEN", "")

PROMPTS = [
    "What is machine learning?",
    "Explain neural networks.",
    "What are the applications of AI?",
    "Describe deep learning architectures.",
    "What is natural language processing?",
]

def main():
    print("=" * 60)
    print(f"Model: {MODEL}")
    print(f"Duration: {RUN_DURATION_MINUTES} minutes")
    print("=" * 60)
    
    # Initialize client
    if HF_TOKEN:
        client = InferenceClient(token=HF_TOKEN)
        print(f"✓ Using HF token (length: {len(HF_TOKEN)})")
    else:
        client = InferenceClient()
        print("⚠ No HF_TOKEN set")
    
    end = time.time() + RUN_DURATION_MINUTES * 60
    n = 0
    errors = 0
    
    print(f"Starting workload...")
    
    while time.time() < end:
        for prompt in PROMPTS:
            if time.time() >= end:
                break
            
            try:
                completion = client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=50,
                    temperature=0.7
                )
                
                response_text = completion.choices[0].message.content
                print(f"✓ Request {n+1}: {response_text[:60]}...")
                n += 1
                
                if n % 10 == 0:
                    print(f"Progress: {n} requests completed")
                
                time.sleep(2)
                
            except Exception as e:
                print(f"❌ Request error: {e}")
                errors += 1
                time.sleep(5)
    
    print("=" * 60)
    print(f"Complete! Successful: {n}, Failed: {errors}")
    print("=" * 60)

if __name__ == "__main__":
    main()
"""

def ensure_image():
    """Build Docker image with huggingface_hub"""
    log("Building Docker image...")
    
    Path("remote_inference.py").write_text(textwrap.dedent(REMOTE_INFERENCE_PY).lstrip())
    
    dockerfile = r"""
FROM python:3.10-slim
RUN pip install --no-cache-dir huggingface_hub requests
WORKDIR /app
COPY remote_inference.py /app/remote_inference.py
CMD ["python", "/app/remote_inference.py"]
"""
    
    Path("Dockerfile.remote").write_text(textwrap.dedent(dockerfile).lstrip())
    must("docker build -t hf-remote-inference -f Dockerfile.remote .", "docker build")
    
    # Pull tcpdump image
    run_cmd("docker pull nicolaka/netshoot >/dev/null 2>&1 || true")
    log("✓ Docker images ready")

def start_inference_container(model_name: str):
    """Start container that makes remote HuggingFace API calls"""
    safe = model_to_safe_name(model_name)
    cname = f"hf-inference-{safe}"
    docker_rm(cname)
    
    cmd = f'''docker run -d --name {cname} \
      -e MODEL="{model_name}" \
      -e HF_TOKEN="{HF_TOKEN}" \
      -e RUN_DURATION_MINUTES="{RUN_DURATION_MINUTES}" \
      hf-remote-inference'''
    
    log(f"[{safe}] Starting remote inference container...")
    must(cmd, f"[{safe}] start inference container")
    
    time.sleep(2)
    return cname

def start_capture(inference_container: str, model_name: str):
    """Start tcpdump sidecar to capture HuggingFace API traffic"""
    safe = model_to_safe_name(model_name)
    tcpdump_container = f"tcpdump-{safe}"
    pcap_file = f"/captures/{safe}.pcap"
    docker_rm(tcpdump_container)
    
    time.sleep(2)
    
    # Sidecar shares network namespace with inference container
    cmd = f'''docker run -d --name {tcpdump_container} \
      --net=container:{inference_container} \
      -v "{CAPTURES_HOST_ABS}:/captures" \
      --cap-add=NET_RAW --cap-add=NET_ADMIN \
      nicolaka/netshoot tcpdump -i any -s0 -U -w {pcap_file}'''
    
    out, err, rc = run_cmd(cmd)
    if rc != 0:
        log(f"[{safe}] ❌ Capture failed: {err.strip()}")
        return False
    
    time.sleep(2)
    check_logs, _, _ = run_cmd(f"docker logs {tcpdump_container} 2>&1")
    if "listening on" in check_logs.lower():
        log(f"[{safe}] ✓ Packet capture active -> {safe}.pcap")
        return True
    else:
        log(f"[{safe}] ⚠ tcpdump logs: {check_logs[:200]}")
        return False

def stop_capture(model_name: str):
    """Stop tcpdump sidecar"""
    safe = model_to_safe_name(model_name)
    tcpdump_container = f"tcpdump-{safe}"
    log(f"[{safe}] Stopping capture...")
    run_cmd(f"docker stop {tcpdump_container} >/dev/null 2>&1 || true")
    time.sleep(1)
    docker_rm(tcpdump_container)

def wait_for_completion(inference_container: str, model_name: str):
    """Wait for inference container to finish"""
    safe = model_to_safe_name(model_name)
    log(f"[{safe}] Waiting for workload to complete...")
    
    # Follow logs in real-time
    cmd = f"docker logs -f {inference_container}"
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    try:
        for line in process.stdout:
            print(f"[{safe}] {line.rstrip()}")
    except KeyboardInterrupt:
        log(f"[{safe}] Interrupted by user")
    finally:
        process.terminate()

def collect_logs(inference_container: str, model_name: str):
    """Save container logs"""
    safe = model_to_safe_name(model_name)
    out, err, rc = run_cmd(f"docker logs {inference_container}")
    if rc == 0:
        p = LOGS_DIR / f"{safe}.log"
        p.write_text(out)
        log(f"[{safe}] Logs saved -> {p}")

def run_experiment():
    safe = model_to_safe_name(MODEL)
    inf_container = None
    
    try:
        # Start inference container
        inf_container = start_inference_container(MODEL)
        
        # Start capture sidecar
        start_capture(inf_container, MODEL)
        
        # Wait for workload to complete
        wait_for_completion(inf_container, MODEL)
        
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
            log(f"[{safe}] ✓ PCAP created: {pcap} ({size_mb:.2f} MB)")
        else:
            log(f"[{safe}] ⚠ WARNING: PCAP not found")

if __name__ == "__main__":
    log("=" * 60)
    log("LLM Network Traffic Capture - Docker + Remote HuggingFace API")
    log("=" * 60)
    log(f"Model: {MODEL}")
    log(f"Duration: {RUN_DURATION_MINUTES} minutes")
    log(f"HF_TOKEN set: {'Yes' if HF_TOKEN else 'No'}")
    log("=" * 60)
    
    ensure_image()
    run_experiment()
    
    log("=" * 60)
    log("Experiment complete!")
    log("=" * 60)
