#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time

import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "ollama-gpu")
OLLAMA_PORT = int(os.environ.get("OLLAMA_PORT", "11434"))
OLLAMA_URL  = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate"


def stream_prompt(model: str, prompt: str, index: int, max_tokens: int):
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {
            "num_predict": max_tokens,
        },
    }

    print(f"[client] Sending prompt #{index} to {model} via Ollama...", flush=True)

    tokens = []
    timing = []  # [{"t": seconds_since_first_chunk, "text": chunk}, ...]

    try:
        with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=300) as r:
            r.raise_for_status()
            t0 = time.time()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    event = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                if event.get("done"):
                    break

                tok = event.get("response", "")
                if tok:
                    t_rel = time.time() - t0
                    tokens.append(tok)
                    timing.append({"t": t_rel, "text": tok})
    except Exception as e:
        print(json.dumps({"index": index, "error": str(e)}), flush=True)
        sys.exit(1)

    response = "".join(tokens)
    print(
        f"[client] ✓ Stream complete — {len(tokens)} chunks, {len(response)} chars",
        flush=True,
    )

    # Final JSON line with timestamps
    print(
        json.dumps(
            {
                "index": index,
                "response": response,
                "timing": timing,
            }
        ),
        flush=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--max-tokens", type=int, default=512)
    args = ap.parse_args()

    stream_prompt(args.model, args.prompt, args.index, args.max_tokens)


if __name__ == "__main__":
    main()