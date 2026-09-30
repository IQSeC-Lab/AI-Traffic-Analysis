"""
Model downloader, ported from 1-Model_downloader/downloader.py.

Downloads a HuggingFace model into MODELS_DIR/<org>-<name>/ as a flat copy,
which is where the data collector mounts models from. Downloads run one at
a time in the background (like downloader.sh); extra requests wait in a queue.
Re-downloading an interrupted model resumes it.
"""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from huggingface_hub import snapshot_download
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError, RevisionNotFoundError
from pydantic import BaseModel, Field

from console import console
from storage import MODEL_ID_PATTERN, MODELS_DIR, estimate_gpu_memory_mb, has_weights, model_dir_name

from . import store

IGNORE_PATTERNS = ["*.msgpack", "*.h5", "flax_model*", "tf_model*"]  # skip non-PyTorch weights
MARKER_FILE     = ".mallm-model.json"   # records the repo id, since folder names drop the "/"
ACTIVE_STATUSES = {"queued", "preparing", "downloading"}


class DownloadRequest(BaseModel):
    model: str = Field(..., pattern=MODEL_ID_PATTERN, description="HuggingFace repo id, e.g. org/model-name")
    revision: str | None = Field(None, description="Branch or commit hash (default: main)")


def already_downloaded(target: Path) -> bool:
    """A model directory is complete when it has a config.json and at least one weight file."""
    return target.exists() and (target / "config.json").exists() and has_weights(target)


def _dir_size(path: Path, include_cache: bool = True) -> int:
    total = 0
    for f in path.rglob("*"):
        if not include_cache and ".cache" in f.relative_to(path).parts:
            continue
        try:
            if f.is_file():
                total += f.stat().st_size
        except FileNotFoundError:   # moved while downloading
            pass
    return total


def _describe(e: Exception) -> str:
    if isinstance(e, GatedRepoError):
        return "Gated model: accept its license on huggingface.co and use a token that has access."
    if isinstance(e, RepositoryNotFoundError):
        return "Model not found on HuggingFace (or it is private and the token has no access)."
    if isinstance(e, RevisionNotFoundError):
        return "Revision not found."
    return str(e).strip().splitlines()[0][:300] if str(e).strip() else type(e).__name__


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# One download at a time, like downloader.sh
_slot = threading.Semaphore(1)


class Download:
    def __init__(self, req: DownloadRequest):
        self.id       = uuid.uuid4().hex[:8]
        self.model    = req.model
        self.revision = req.revision
        self.target   = MODELS_DIR / model_dir_name(req.model)
        self.status   = "queued"
        self.error: str | None = None
        self.total_bytes: int | None = None
        self.created_at  = _now()
        self.finished_at: str | None = None
        self._token  = store.hf_token()   # saved in Settings, else HF_TOKEN
        self._thread = threading.Thread(target=self._run, name=f"download-{self.id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def summary(self) -> dict:
        if self.status == "downloading" and self.target.exists():
            downloaded = _dir_size(self.target)
        elif self.status == "completed":
            downloaded = self.total_bytes
        else:
            downloaded = 0
        return {
            "id": self.id,
            "model": self.model,
            "revision": self.revision,
            "status": self.status,
            "error": self.error,
            "downloaded_bytes": downloaded,
            "total_bytes": self.total_bytes,
            "target": str(self.target),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }

    def _run(self) -> None:
        existed_before = self.target.exists()
        with _slot:
            try:
                self.status = "preparing"
                args = dict(
                    repo_id=self.model,
                    local_dir=str(self.target),
                    revision=self.revision,
                    token=self._token,
                    ignore_patterns=IGNORE_PATTERNS,
                )
                # Dry run lists the files first: validates access and gives the total size.
                files = snapshot_download(**args, dry_run=True)
                self.total_bytes = sum(f.file_size or 0 for f in files)

                self.status = "downloading"
                console(f"[downloader] Downloading '{self.model}' → {self.target}")
                snapshot_download(**args)
                (self.target / MARKER_FILE).write_text(json.dumps({
                    "model": self.model,
                    "revision": self.revision,
                    "downloaded_at": _now(),
                }))
                self.status = "completed"
                console(f"[downloader] ✓ Download complete → {self.target}")
            except Exception as e:
                self.error = _describe(e)
                self.status = "failed"
                console(f"[downloader] ✗ {self.model}: {e}")
                # Remove a folder this download created if nothing was saved in it;
                # partial downloads are kept so a retry resumes them.
                if not existed_before and self.target.exists() and _dir_size(self.target, include_cache=False) == 0:
                    shutil.rmtree(self.target, ignore_errors=True)
            finally:
                self._token = None
                self.finished_at = _now()


_downloads: dict[str, Download] = {}
_lock = threading.Lock()


class AlreadyDownloaded(Exception):
    pass


class DownloadConflict(Exception):
    pass


def start(req: DownloadRequest) -> Download:
    target = MODELS_DIR / model_dir_name(req.model)
    if already_downloaded(target):
        raise AlreadyDownloaded(f"{req.model} is already downloaded at {target}.")
    with _lock:
        if any(d.target == target and d.status in ACTIVE_STATUSES for d in _downloads.values()):
            raise DownloadConflict(f"{req.model} is already downloading.")
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        download = Download(req)
        _downloads[download.id] = download
        download.start()
    return download


def get(download_id: str) -> Download | None:
    return _downloads.get(download_id)


def all_downloads() -> list[Download]:
    return sorted(_downloads.values(), key=lambda d: d.created_at, reverse=True)


class ModelInUse(Exception):
    pass


def delete_model(folder: str) -> bool:
    """Delete a downloaded model's folder. False if there is no such model."""
    path = MODELS_DIR / folder
    if "/" in folder or folder.startswith(".") or path.resolve().parent != MODELS_DIR or not path.is_dir():
        return False
    if any(d.target == path and d.status in ACTIVE_STATUSES for d in _downloads.values()):
        raise ModelInUse(f"{folder} is still downloading.")
    shutil.rmtree(path)
    return True


def list_models() -> list[dict]:
    """Every model folder in MODELS_DIR, including ones fetched with the CLI downloader."""
    if not MODELS_DIR.exists():
        return []
    downloading = {d.target for d in _downloads.values() if d.status in ACTIVE_STATUSES}
    models = []
    for path in sorted(MODELS_DIR.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        try:
            marker = json.loads((path / MARKER_FILE).read_text())
        except (OSError, ValueError):
            marker = {}
        models.append({
            "folder": path.name,
            "model": marker.get("model"),
            "size_bytes": _dir_size(path),
            "complete": already_downloaded(path),
            "gpu_memory_mb": estimate_gpu_memory_mb(path) if has_weights(path) else None,
            "downloading": path in downloading,
        })
    return models
