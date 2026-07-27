#!/usr/bin/env python3
"""
inference_server.py
Runs inside the llm-toolbox container on llm-net.
Loads model from a host-mounted read-only path. Zero network calls.

Usage (inside container):
    python3 inference_server.py \
        --model-name  prithivMLmods/Evac-Opus-14B-Exp \
        --model-path  /models/prithivMLmods-Evac-Opus-14B-Exp
"""

import argparse
import json
from threading import Thread

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TextIteratorStreamer,
)
import uvicorn

app = FastAPI()

# ── Sampling temperature (change this between runs) ──────────────────────────
TEMPERATURE = 0.9
# ─────────────────────────────────────────────────────────────────────────────

MODEL_NAME = None
model      = None
tokenizer  = None


class PromptRequest(BaseModel):
    prompt:     str
    max_tokens: int = 1024
    stream:     bool = True   # default matches ChatGPT behaviour


@app.get("/health")
async def health():
    return {"status": "healthy", "model": MODEL_NAME}


# ── Non-streaming fallback (kept for compatibility) ──────────────────────────
@app.post("/generate/sync")
async def generate_sync(req: PromptRequest):
    """Single-shot JSON response – useful for unit tests, not for fingerprinting."""
    inputs = tokenizer(req.prompt, return_tensors="pt").to(model.device)
    output_ids = model.generate(
        input_ids=inputs["input_ids"],
        attention_mask=inputs["attention_mask"],
        max_new_tokens=req.max_tokens,
        do_sample=True,
        temperature=TEMPERATURE,
        pad_token_id=tokenizer.eos_token_id,
    )
    # Decode only the newly generated tokens (strip the prompt)
    new_ids = output_ids[0][inputs["input_ids"].shape[-1]:]
    text = tokenizer.decode(new_ids, skip_special_tokens=True)
    return {"response": text}


# ── Streaming endpoint – mirrors ChatGPT / OpenAI SSE wire format ────────────
@app.post("/generate")
async def generate_text(req: PromptRequest):
    """
    Streams tokens as Server-Sent Events (SSE) using the same
    `data: {...}` / `data: [DONE]` format as the OpenAI Chat API.

    Each SSE frame:
        data: {"choices":[{"delta":{"content":"<token>"},"index":0,"finish_reason":null}]}

    Final frame:
        data: [DONE]

    Content-Type: text/event-stream  (keeps the TCP connection open)
    Transfer-Encoding: chunked       (no Content-Length; bytes pushed per token)
    """
    inputs = tokenizer(
        req.prompt,
        return_tensors="pt",
        padding=True,
    ).to(model.device)

    streamer = TextIteratorStreamer(
        tokenizer,
        skip_prompt=True,          # don't re-emit the input tokens
        skip_special_tokens=True,
    )

    generation_kwargs = dict(
        input_ids=inputs["input_ids"],
        attention_mask=inputs["attention_mask"],
        max_new_tokens=req.max_tokens,
        do_sample=True,
        temperature=TEMPERATURE,
        pad_token_id=tokenizer.eos_token_id,
        streamer=streamer,
    )
    
    # Run the blocking model.generate() in a background thread so we don't
    # stall the async event loop.
    thread = Thread(target=model.generate, kwargs=generation_kwargs, daemon=True)
    thread.start()

    async def event_stream():
        try:
            for token_text in streamer:          # yields as each token is ready
                if token_text:
                    chunk = {
                        "choices": [{
                            "delta": {"content": token_text},
                            "index": 0,
                            "finish_reason": None,
                        }]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
        finally:
            thread.join(timeout=0)               # clean-up; thread may already be done
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "Connection":       "keep-alive",
            # Prevents nginx / any upstream proxy from buffering SSE chunks
            "X-Accel-Buffering": "no",
        },
    )


# ── Model loading ─────────────────────────────────────────────────────────────
def load_model(model_path: str, model_name: str):
    global model, tokenizer, MODEL_NAME
    MODEL_NAME = model_name

    print(f"[server] Loading tokenizer from: {model_path}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print("[server] Loading model weights...", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        device_map="auto",
        torch_dtype="auto",
        low_cpu_mem_usage=True,
        local_files_only=True,
    )
    # NOTE: we no longer wrap in pipeline() so we can pass a streamer directly
    # to model.generate() without fighting the pipeline abstraction.
    print(f"[server] ✓ Model ready: {model_name}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-name", required=True, help="Human-readable model label")
    ap.add_argument("--model-path", required=True, help="Absolute path inside container")
    ap.add_argument("--host",       default="0.0.0.0")
    ap.add_argument("--port",       type=int, default=8000)
    args = ap.parse_args()
    load_model(args.model_path, args.model_name)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()