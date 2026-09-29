"""
Settings saved on the host in DATA_DIR/settings.json.
The file is owner-readable only because it holds the HuggingFace token.
"""

import json
import os
from pathlib import Path

from storage import DATA_DIR

SETTINGS_FILE = DATA_DIR / "settings.json"


def load() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def update(**values) -> None:
    """Merge values into the settings file. A value of None removes that key."""
    data = {**load(), **values}
    data = {k: v for k, v in data.items() if v is not None}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(SETTINGS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(SETTINGS_FILE, 0o600)


def hf_token() -> str | None:
    """The saved token, else the HF_TOKEN environment variable."""
    return load().get("hf_token") or os.environ.get("HF_TOKEN") or None


# ── Where experiment results go ──────────────────────────────────────────────

def results_root() -> Path:
    """The folder new experiment results are saved in (Settings → Storage). DATA_DIR by default."""
    saved = load().get("results_dir")
    return Path(saved) if saved else DATA_DIR


def results_roots() -> list[Path]:
    """Every results folder used so far, so earlier runs stay listed after the folder changes."""
    history = [Path(p) for p in load().get("results_dirs", [])]
    return list(dict.fromkeys([DATA_DIR, results_root(), *history]))


def set_results_root(path: Path | None) -> None:
    """Use `path` for new results (None = back to the default)."""
    history = load().get("results_dirs", [])
    if path is not None and str(path) not in history:
        history = [*history, str(path)]
    update(results_dir=str(path) if path else None, results_dirs=history or None)
