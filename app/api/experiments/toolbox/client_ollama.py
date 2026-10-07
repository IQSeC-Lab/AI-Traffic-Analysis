#!/usr/bin/env python3
"""
client_ollama.py
The client of client.py for an Ollama server: waits for it, loads the model, sends one
prompt to /api/generate and reads the stream line by line as it arrives, then prints the
same JSON result (response and per-chunk timing). Standard library only, so it runs in a
plain Python image.

Usage (inside a container on the run's network):
    python3 client_ollama.py \
        --host  mallm-<run>-w1-llm \
        --port  8000 \
        --model llama3.2:3b \
        --index 1 \
        --prompt-file /prompts/prompt_01.txt
"""

import argparse
import http.client
import json
import sys
import time


def wait_for_server(host: str, port: int, timeout: int = 300) -> bool:
    deadline = time.time() + timeout
    print(f"[client] Waiting for Ollama at {host}:{port} ...", flush=True)
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/api/version")
            r = conn.getresponse()
            ready = r.status == 200
            r.read()
            conn.close()
            if ready:
                return True
        except Exception:
            pass
        time.sleep(2)
    print(f"[client] ❌ Server timeout after {timeout}s", flush=True)
    return False


def load_model(host: str, port: int, model: str, timeout: int = 900) -> None:
    """A generate request without a prompt loads the model and returns. The stream that is
    measured then starts from a loaded model, as it does with the transformers server."""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request("POST", "/api/generate", body=json.dumps({"model": model, "keep_alive": -1}).encode(),
                 headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    body = r.read().decode(errors="replace")
    conn.close()
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status}: {body[:300]}")
    print(f"[client] ✓ Server ready — model: {model}", flush=True)


def send_prompt(host: str, port: int, model: str, prompt: str, index: int, max_tokens: int, temperature):
    options = {"num_predict": max_tokens}
    if temperature is not None:
        options["temperature"] = temperature
    body = json.dumps({"model": model, "prompt": prompt, "stream": True, "options": options}).encode("utf-8")

    print(f"[client] Sending prompt #{index} ({len(prompt)} chars) — NDJSON stream ...", flush=True)

    tokens = []
    timing = []  # [{"t": cumulative_seconds, "dt": inter_chunk_seconds, "text": chunk}, ...]

    try:
        conn = http.client.HTTPConnection(host, port, timeout=300)
        conn.request("POST", "/api/generate", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()

        if resp.status != 200:
            err = resp.read().decode()
            print(json.dumps({"index": index, "error": f"HTTP {resp.status}: {err}"}), flush=True)
            sys.exit(1)

        # One JSON object per line; read a byte at a time to react to each line as it arrives.
        buf = b""
        t0 = time.time()          # stream start (TTFT reference)
        t_prev = None             # previous chunk arrival time
        while True:
            chunk = resp.read(1)
            if not chunk:
                break
            buf += chunk
            if not buf.endswith(b"\n"):
                continue
            line, buf = buf.decode("utf-8").strip(), b""
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = event.get("response", "")
            if text:
                t_now = time.time()
                timing.append({"t": t_now - t0, "dt": t_now - t_prev if t_prev is not None else 0.0, "text": text})
                t_prev = t_now
                tokens.append(text)
            if event.get("done"):
                break
        conn.close()

    except Exception as e:
        print(json.dumps({"index": index, "error": str(e)}), flush=True)
        sys.exit(1)

    response = "".join(tokens)
    print(f"[client] ✓ Stream complete — {len(tokens)} chunks, {len(response)} chars", flush=True)
    # This JSON line is captured by the orchestrator
    print(json.dumps({"index": index, "response": response, "timing": timing}), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host",        required=True)
    ap.add_argument("--port",        type=int, default=8000)
    ap.add_argument("--model",       required=True, help="Ollama model, e.g. llama3.2:3b")
    ap.add_argument("--index",       type=int, required=True)
    ap.add_argument("--prompt-file", required=True, help="Path to plain-text prompt file")
    ap.add_argument("--max-tokens",  type=int, default=512)
    ap.add_argument("--temperature", type=float, default=None)
    args = ap.parse_args()

    prompt = open(args.prompt_file).read()

    if not wait_for_server(args.host, args.port):
        sys.exit(1)
    try:
        load_model(args.host, args.port, args.model)
    except Exception as e:
        print(json.dumps({"index": args.index, "error": f"Could not load {args.model}: {e}"}), flush=True)
        sys.exit(1)

    send_prompt(args.host, args.port, args.model, prompt, args.index, args.max_tokens, args.temperature)


if __name__ == "__main__":
    main()
