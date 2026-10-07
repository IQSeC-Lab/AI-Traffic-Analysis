#!/usr/bin/env python3
"""Force every LLM field in generated task YAML configs to a single target
model. jsonl2yaml.py's fill_defaults() only fills EMPTY llm fields, but the
raw multiagentbench/*.jsonl datasets have individual agents pre-populated
with specific models (gpt-4o, gpt-3.5-turbo, ...) from the paper's original
multi-model experiments -- those never get overridden by --default_llm and
will try to hit the real OpenAI API with no credentials, retrying 5x with
exponential backoff on every single turn.
"""

import argparse
import glob

import yaml


def normalize(path: str, model: str) -> bool:
    with open(path) as f:
        data = yaml.safe_load(f)
    changed = False
    if data.get("llm") != model:
        data["llm"] = model
        changed = True
    for agent in data.get("agents", []):
        if agent.get("llm") != model:
            agent["llm"] = model
            changed = True
    metrics = data.get("metrics", {})
    if isinstance(metrics, dict) and metrics.get("evaluate_llm") != model:
        metrics["evaluate_llm"] = model
        changed = True
    if changed:
        with open(path, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--model", default="ollama/llama3.2:3b")
    args = parser.parse_args()

    files = sorted(glob.glob(f"{args.folder}/*.yaml"))
    n_changed = sum(normalize(f, args.model) for f in files)
    print(f"normalized {n_changed}/{len(files)} files in {args.folder} to model={args.model}")


if __name__ == "__main__":
    main()
