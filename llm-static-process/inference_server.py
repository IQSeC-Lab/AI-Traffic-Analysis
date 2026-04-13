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

from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
import uvicorn

app = FastAPI()

MODEL_NAME = None
generator  = None
tokenizer  = None


class PromptRequest(BaseModel):
    prompt:     str
    max_tokens: int = 512


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


def load_model(model_path: str, model_name: str):
    global generator, tokenizer, MODEL_NAME
    MODEL_NAME = model_name
    print(f"[server] Loading tokenizer from: {model_path}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    print(f"[server] Loading model weights...", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        device_map="auto",
        torch_dtype="auto",
        low_cpu_mem_usage=True,
        local_files_only=True,
    )
    generator = pipeline("text-generation", model=model, tokenizer=tokenizer)
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
