#!/usr/bin/env python3
"""
client.py
Runs inside the llm-toolbox container on llm-net.
Waits for the inference server, sends one prompt, prints JSON result, exits.

Usage (inside container):
    python3 client.py \
        --host  llm-prithivMLmods-Evac-Opus-14B-Exp \
        --port  8000 \
        --index 1 \
        --prompt-file /prompts/prompt_01.txt
"""

import argparse
import json
import sys
import time
import urllib.request


def wait_for_server(host: str, port: int, timeout: int = 900) -> bool:
    deadline = time.time() + timeout
    print(f"[client] Waiting for server at {host}:{port} ...", flush=True)
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=5) as r:
                if r.status == 200:
                    info = json.loads(r.read().decode())
                    print(f"[client] ✓ Server ready — model: {info.get('model')}", flush=True)
                    return True
        except Exception:
            pass
        time.sleep(5)
    print(f"[client] ❌ Server timeout after {timeout}s", flush=True)
    return False


def send_prompt(host: str, port: int, prompt: str, index: int, max_tokens: int):
    url  = f"http://{host}:{port}/generate"
    data = json.dumps({"prompt": prompt, "max_tokens": max_tokens}).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
    )
    print(f"[client] Sending prompt #{index} ({len(prompt)} chars)...", flush=True)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body = json.loads(r.read().decode("utf-8"))
            response = body.get("response", "")
            print(f"[client] ✓ Response received ({len(response)} chars)", flush=True)
            # This JSON line is captured by the orchestrator
            print(json.dumps({"index": index, "response": response}), flush=True)
    except Exception as e:
        print(json.dumps({"index": index, "error": str(e)}), flush=True)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host",        required=True)
    ap.add_argument("--port",        type=int, default=8000)
    ap.add_argument("--index",       type=int, required=True)
    ap.add_argument("--prompt-file", required=True, help="Path to plain-text prompt file")
    ap.add_argument("--max-tokens",  type=int, default=512)
    args = ap.parse_args()

    prompt = open(args.prompt_file).read()

    if not wait_for_server(args.host, args.port):
        sys.exit(1)

    send_prompt(args.host, args.port, prompt, args.index, args.max_tokens)


if __name__ == "__main__":
    main()
