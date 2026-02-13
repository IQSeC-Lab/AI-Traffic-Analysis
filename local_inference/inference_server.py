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
