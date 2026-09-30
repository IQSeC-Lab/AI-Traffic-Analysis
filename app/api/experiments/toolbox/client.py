#!/usr/bin/env python3
"""
client.py
Runs inside the llm-toolbox container on llm-net.
Waits for the inference server, sends one prompt, consumes the SSE stream
token-by-token (mirroring a ChatGPT browser session), prints JSON result, exits.

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
import http.client


def wait_for_server(host: str, port: int, timeout: int = 900) -> bool:
    deadline = time.time() + timeout
    print(f"[client] Waiting for server at {host}:{port} ...", flush=True)
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/health")
            r = conn.getresponse()
            if r.status == 200:
                info = json.loads(r.read().decode())
                print(f"[client] ✓ Server ready — model: {info.get('model')}", flush=True)
                conn.close()
                return True
            conn.close()
        except Exception:
            pass
        time.sleep(5)
    print(f"[client] ❌ Server timeout after {timeout}s", flush=True)
    return False


def send_prompt(host: str, port: int, prompt: str, index: int, max_tokens: int):
    """
    Opens a persistent HTTP connection and reads the SSE stream line-by-line,
    exactly as a browser EventSource would. Each 'data: {...}' line is parsed
    immediately upon arrival — no buffering of the full response body.

    This produces the same network behaviour as a ChatGPT browser session:
      - Long-lived TCP connection (kept open for the entire generation)
      - Many small TCP segments arriving at token-generation rate
      - Transfer-Encoding: chunked (no Content-Length)
      - Final frame 'data: [DONE]' closes the logical stream
    """
    url  = "/generate"
    body = json.dumps({"prompt": prompt, "max_tokens": max_tokens}).encode("utf-8")

    print(f"[client] Sending prompt #{index} ({len(prompt)} chars) — SSE stream ...", flush=True)

    tokens = []
    timing = []  # [{"t": cumulative_seconds, "dt": inter_token_seconds, "text": token}, ...]

    try:
        conn = http.client.HTTPConnection(host, port, timeout=300)
        conn.request(
            "POST", url, body=body,
            headers={
                "Content-Type":  "application/json",
                "Accept":        "text/event-stream",   # signal we want SSE
                "Cache-Control": "no-cache",
            },
        )
        resp = conn.getresponse()

        if resp.status != 200:
            err = resp.read().decode()
            print(json.dumps({"index": index, "error": f"HTTP {resp.status}: {err}"}), flush=True)
            sys.exit(1)

        # ── Read the stream line-by-line ──────────────────────────────────────
        # http.client gives us a file-like socket; we read until we see the
        # sentinel 'data: [DONE]' that the server sends after the last token.
        buf = b""
        t0 = time.time()          # stream start (TTFT reference)
        t_prev = None             # previous token arrival time
        while True:
            # Read one byte at a time so we react to each '\n' immediately,
            # matching browser EventSource behaviour (no internal buffering).
            chunk = resp.read(1)
            if not chunk:
                break          # connection closed unexpectedly

            buf += chunk
            if buf.endswith(b"\n"):
                line = buf.decode("utf-8").rstrip("\r\n")
                buf  = b""

                if not line:
                    continue   # blank separator line between SSE events

                if line.startswith("data: "):
                    payload = line[6:]

                    if payload == "[DONE]":
                        break  # generation complete

                    try:
                        event = json.loads(payload)
                        token_text = (
                            event.get("choices", [{}])[0]
                                 .get("delta", {})
                                 .get("content", "")
                        )
                        if token_text:
                            t_now = time.time()
                            t_rel = t_now - t0
                            dt = t_now - t_prev if t_prev is not None else 0.0
                            t_prev = t_now

                            tokens.append(token_text)
                            timing.append({
                                "t": t_rel,
                                "dt": dt,
                                "text": token_text,
                            })
                    except json.JSONDecodeError:
                        pass   # ignore malformed frames

        conn.close()

    except Exception as e:
        print(json.dumps({"index": index, "error": str(e)}), flush=True)
        sys.exit(1)

    response = "".join(tokens)
    print(f"[client] ✓ Stream complete — {len(tokens)} tokens, {len(response)} chars", flush=True)
    # This JSON line is captured by the orchestrator
    print(json.dumps({
        "index": index,
        "response": response,
        "timing": timing,
    }), flush=True)


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