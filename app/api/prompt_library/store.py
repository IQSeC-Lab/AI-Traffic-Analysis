"""
The prompt library: the 60 built-in prompts plus prompts users add, each in a category.

Custom prompts live in DATA_DIR/prompts.json. They are numbered after the built-ins
(61, 62, ...) and numbers are never reused, so a prompt number in a past run's files
always means the same prompt. Built-in prompts are read-only.
"""

import json
import os
import textwrap
import threading
from datetime import datetime

from storage import DATA_DIR

from .builtin import CATEGORIES, PROMPTS, category_of

LIBRARY_FILE = DATA_DIR / "prompts.json"
FIRST_CUSTOM_NUMBER = len(PROMPTS) + 1

_lock = threading.Lock()

_BUILTIN = [
    {"number": n, "category": category_of(n), "text": textwrap.dedent(p).strip(), "builtin": True}
    for n, p in enumerate(PROMPTS, start=1)
]


class ReadOnlyPrompt(Exception):
    pass


def _load() -> dict:
    try:
        return json.loads(LIBRARY_FILE.read_text())
    except FileNotFoundError:
        return {"next_number": FIRST_CUSTOM_NUMBER, "prompts": []}


def _save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LIBRARY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, LIBRARY_FILE)


def _custom(data: dict) -> list[dict]:
    return [{**p, "builtin": False} for p in data["prompts"]]


def all_prompts() -> list[dict]:
    return _BUILTIN + _custom(_load())


def get(number: int) -> dict | None:
    return next((p for p in all_prompts() if p["number"] == number), None)


def snapshot(numbers: list[int]) -> dict[int, dict]:
    """The text to send and the category of each prompt, fixed at the start of a run.
    Built-in prompts are sent exactly as in 2-Data-Collector (not dedented)."""
    library = {p["number"]: p for p in all_prompts()}
    return {
        n: {
            "text": PROMPTS[n - 1] if library[n]["builtin"] else library[n]["text"],
            "category": library[n]["category"],
        }
        for n in numbers
    }


def categories() -> list[dict]:
    """Built-in categories first, then custom ones in the order they were first used."""
    counts: dict[str, int] = {name: 0 for name, _, _ in CATEGORIES}
    for p in all_prompts():
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    builtin = {name for name, _, _ in CATEGORIES}
    return [{"name": name, "count": n, "builtin": name in builtin} for name, n in counts.items()]


def add(category: str, text: str) -> dict:
    with _lock:
        data = _load()
        prompt = {
            "number": data["next_number"],
            "category": category,
            "text": text,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        data["prompts"].append(prompt)
        data["next_number"] += 1
        _save(data)
    return {**prompt, "builtin": False}


def update(number: int, category: str, text: str) -> dict | None:
    if number < FIRST_CUSTOM_NUMBER:
        raise ReadOnlyPrompt(f"Prompt #{number} is built in and can't be changed.")
    with _lock:
        data = _load()
        prompt = next((p for p in data["prompts"] if p["number"] == number), None)
        if prompt is None:
            return None
        prompt.update(category=category, text=text, updated_at=datetime.now().isoformat(timespec="seconds"))
        _save(data)
    return {**prompt, "builtin": False}


def delete(number: int) -> bool:
    if number < FIRST_CUSTOM_NUMBER:
        raise ReadOnlyPrompt(f"Prompt #{number} is built in and can't be deleted.")
    with _lock:
        data = _load()
        kept = [p for p in data["prompts"] if p["number"] != number]
        if len(kept) == len(data["prompts"]):
            return False
        data["prompts"] = kept   # next_number is unchanged, so the number is never reused
        _save(data)
    return True
