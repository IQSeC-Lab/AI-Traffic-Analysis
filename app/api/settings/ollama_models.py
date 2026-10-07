"""
Ollama models: pulled from the Ollama library into OLLAMA_DIR, listed and deleted.

The experiments run Ollama in a container with OLLAMA_DIR mounted as /root/.ollama, on a
network without internet, so the models have to be on the host first. There is no Ollama
on the host to pull them with, so this speaks the registry's HTTP API itself: a model is
a manifest (a JSON list of layers) and one blob per layer, addressed by its sha256.

    OLLAMA_DIR/models/manifests/registry.ollama.ai/<namespace>/<name>/<tag>
    OLLAMA_DIR/models/blobs/sha256-<hex>

That is the layout `ollama pull` writes, so Ollama finds the models as its own.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from console import console
from storage import OLLAMA_DIR

REGISTRY = "https://registry.ollama.ai"
REGISTRY_HOST = "registry.ollama.ai"
# name, namespace/name, either with :tag — e.g. llama3.2:3b, mistral, someone/model:latest
MODEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9._-]+)?(:[A-Za-z0-9._-]+)?$"
MANIFEST_TYPE = "application/vnd.docker.distribution.manifest.v2+json"
ACTIVE_STATUSES = {"queued", "preparing", "downloading"}
CHUNK = 1 << 20
TIMEOUT = 60
USER_AGENT = "rogueagent-app"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def split(model: str) -> tuple[str, str]:
    """(repository, tag) of a model name: llama3.2:3b -> ("library/llama3.2", "3b")."""
    name, _, tag = model.partition(":")
    return (name if "/" in name else f"library/{name}"), tag or "latest"


def normalize(model: str) -> str:
    """The name Ollama shows for a model: the tag is always there, the library namespace never."""
    repo, tag = split(model.strip())
    return f"{repo.removeprefix('library/')}:{tag}"


def _manifests_dir() -> Path:
    return OLLAMA_DIR / "models" / "manifests" / REGISTRY_HOST


def _manifest_path(model: str) -> Path:
    repo, tag = split(model)
    return _manifests_dir() / repo / tag


def _blob_path(digest: str) -> Path:
    return OLLAMA_DIR / "models" / "blobs" / digest.replace(":", "-")


def _layers(manifest: dict) -> list[dict]:
    """Every blob of a model: its layers (the weights, template, parameters) and its config."""
    layers = list(manifest.get("layers") or [])
    if manifest.get("config"):
        layers.append(manifest["config"])
    return [layer for layer in layers if re.fullmatch(r"sha256:[0-9a-f]{64}", str(layer.get("digest")))]


def _read_manifest(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def model_bytes(model: str) -> int | None:
    """Size of a pulled model. None when it isn't pulled, or a blob of it is missing."""
    manifest = _read_manifest(_manifest_path(model))
    if manifest is None:
        return None
    layers = _layers(manifest)
    if not layers or not all(_blob_path(layer["digest"]).is_file() for layer in layers):
        return None
    return sum(int(layer.get("size") or 0) for layer in layers)


def gpu_memory_mb(size_bytes: int) -> int:
    """Rough GPU memory Ollama needs for a model: its weights (+15%) plus 1.5 GB of context."""
    return int(size_bytes / 2**20 * 1.15 + 1536)


def reserve_mb(model: str, on_gpu: bool) -> int:
    """GPU memory a run reserves for a model (0 on the CPU). ValueError when it isn't downloaded."""
    size = model_bytes(model)
    if size is None:
        raise ValueError(f"Ollama model not downloaded: {model}. Download it in Settings, under Ollama models.")
    return gpu_memory_mb(size) if on_gpu else 0


def list_models() -> list[dict]:
    """Every model with a manifest in OLLAMA_DIR, whoever pulled it."""
    root = _manifests_dir()
    pulling = {p.model for p in _pulls.values() if p.status in ACTIVE_STATUSES}
    models = []
    for path in sorted(root.glob("*/*/*")) if root.is_dir() else []:
        if not path.is_file():
            continue
        namespace, name, tag = path.relative_to(root).parts
        model = f"{name}:{tag}" if namespace == "library" else f"{namespace}/{name}:{tag}"
        manifest = _read_manifest(path) or {}
        size = model_bytes(model)
        models.append({
            "model": model,
            "size_bytes": size if size is not None else sum(int(l.get("size") or 0) for l in _layers(manifest)),
            "complete": size is not None,
            "gpu_memory_mb": gpu_memory_mb(size) if size is not None else None,
            "downloading": model in pulling,
        })
    return models


# =============================================================================
# Pulling
# =============================================================================


class PullError(Exception):
    pass


def _open(url: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(request, timeout=TIMEOUT)


def fetch_manifest(model: str) -> tuple[bytes, dict]:
    """The model's manifest from the registry, as sent (Ollama keeps those bytes) and parsed."""
    repo, tag = split(model)
    try:
        with _open(f"{REGISTRY}/v2/{repo}/manifests/{tag}", {"Accept": MANIFEST_TYPE}) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            raise PullError(f"{model} is not in the Ollama library. Check the name and tag on ollama.com/library.")
        raise PullError(f"The Ollama registry answered HTTP {e.code}.")
    except (urllib.error.URLError, OSError) as e:
        raise PullError(f"Could not reach the Ollama registry: {getattr(e, 'reason', e)}")
    try:
        manifest = json.loads(raw)
    except ValueError:
        raise PullError("The Ollama registry sent a manifest that isn't JSON.")
    if not isinstance(manifest, dict) or not _layers(manifest):
        raise PullError(f"The manifest of {model} lists no layers.")
    return raw, manifest


def download_blob(repo: str, layer: dict, progress=lambda n: None, cancelled=lambda: False) -> None:
    """Download one blob into OLLAMA_DIR, resuming a partial file, and check its sha256."""
    digest, size = layer["digest"], int(layer.get("size") or 0)
    target = _blob_path(digest)
    if target.is_file() and (not size or target.stat().st_size == size):
        progress(size)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    have = partial.stat().st_size if partial.exists() else 0
    if size and have > size:   # not this blob's: start over
        partial.unlink()
        have = 0

    sha = hashlib.sha256()
    if have:
        with partial.open("rb") as f:
            while chunk := f.read(CHUNK):
                sha.update(chunk)
        progress(have)
    if not size or have < size:
        try:
            # The registry redirects to where the blob is stored; urllib follows it and keeps the Range
            response = _open(f"{REGISTRY}/v2/{repo}/blobs/{digest}", {"Range": f"bytes={have}-"} if have else None)
        except urllib.error.HTTPError as e:
            raise PullError(f"The Ollama registry answered HTTP {e.code} for a layer.")
        except (urllib.error.URLError, OSError) as e:
            raise PullError(f"Could not reach the Ollama registry: {getattr(e, 'reason', e)}")
        with response:
            if have and response.status != 206:   # the server ignored the Range: it is sending the whole blob
                have = 0
                sha = hashlib.sha256()
                progress(-partial.stat().st_size)
            with partial.open("ab" if have else "wb") as f:
                while True:
                    if cancelled():
                        raise PullError("Cancelled.")
                    try:
                        chunk = response.read(CHUNK)
                    except OSError as e:
                        raise PullError(f"The download stopped: {e}. Download it again to resume.")
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    progress(len(chunk))
    if f"sha256:{sha.hexdigest()}" != digest:
        partial.unlink(missing_ok=True)
        raise PullError("A layer arrived damaged (its checksum doesn't match). Download it again.")
    partial.replace(target)


def pull(model: str, progress=lambda done, total: None, cancelled=lambda: False) -> int:
    """Pull a model from the Ollama library into OLLAMA_DIR. Returns its size in bytes."""
    repo, _ = split(model)
    raw, manifest = fetch_manifest(model)
    layers = _layers(manifest)
    total = sum(int(layer.get("size") or 0) for layer in layers)
    done = 0

    def advance(n: int) -> None:
        nonlocal done
        done += n
        progress(done, total)

    progress(0, total)
    # Largest first: the weights are nearly all of it, so a failure shows up early
    for layer in sorted(layers, key=lambda l: -int(l.get("size") or 0)):
        download_blob(repo, layer, advance, cancelled)
    path = _manifest_path(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)   # last: a model is listed once all of it is here
    return total


# ── Pulls started from Settings ──────────────────────────────────────────────

_slot = threading.Semaphore(1)   # one at a time, like the HuggingFace downloads
_pulls: dict[str, "Pull"] = {}
_lock = threading.Lock()


class Pull:
    def __init__(self, model: str):
        self.id = uuid.uuid4().hex[:8]
        self.model = model
        self.status = "queued"
        self.error: str | None = None
        self.downloaded_bytes = 0
        self.total_bytes: int | None = None
        self.created_at = _now()
        self.finished_at: str | None = None
        self._thread = threading.Thread(target=self._run, name=f"ollama-pull-{self.id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def summary(self) -> dict:
        return {
            "id": self.id,
            "model": self.model,
            "revision": None,
            "status": self.status,
            "error": self.error,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "target": str(OLLAMA_DIR),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }

    def _progress(self, done: int, total: int) -> None:
        self.downloaded_bytes, self.total_bytes = done, total
        self.status = "downloading"

    def _run(self) -> None:
        with _slot:
            try:
                self.status = "preparing"
                console(f"[ollama] Pulling '{self.model}' → {OLLAMA_DIR}")
                pull(self.model, self._progress)
                self.status = "completed"
                console(f"[ollama] ✓ Pulled {self.model}")
            except Exception as e:
                self.error = str(e) if isinstance(e, PullError) else (str(e).strip().splitlines() or [type(e).__name__])[0][:300]
                self.status = "failed"
                console(f"[ollama] ✗ {self.model}: {e}")
            finally:
                self.finished_at = _now()


class AlreadyPulled(Exception):
    pass


class PullConflict(Exception):
    pass


def start(model: str) -> Pull:
    model = normalize(model)
    if model_bytes(model) is not None:
        raise AlreadyPulled(f"{model} is already downloaded.")
    with _lock:
        if any(p.model == model and p.status in ACTIVE_STATUSES for p in _pulls.values()):
            raise PullConflict(f"{model} is already downloading.")
        pulling = Pull(model)
        _pulls[pulling.id] = pulling
        pulling.start()
    return pulling


def all_pulls() -> list[Pull]:
    return sorted(_pulls.values(), key=lambda p: p.created_at, reverse=True)


class ModelInUse(Exception):
    pass


def delete(model: str) -> bool:
    """Delete a pulled model: its manifest, and the blobs no other model uses. False if unknown."""
    model = normalize(model)
    path = _manifest_path(model)
    if not path.is_file() or _manifests_dir().resolve() not in path.resolve().parents:
        return False
    if any(p.model == model and p.status in ACTIVE_STATUSES for p in _pulls.values()):
        raise ModelInUse(f"{model} is still downloading.")
    mine = {layer["digest"] for layer in _layers(_read_manifest(path) or {})}
    path.unlink()
    others = {
        layer["digest"]
        for other in _manifests_dir().glob("*/*/*") if other.is_file()
        for layer in _layers(_read_manifest(other) or {})
    }
    for digest in mine - others:
        blob = _blob_path(digest)
        blob.unlink(missing_ok=True)
        blob.with_name(blob.name + ".partial").unlink(missing_ok=True)
    # Folders left empty by it (the tag was the model's last, the model its namespace's last)
    for folder in (path.parent, path.parent.parent):
        try:
            folder.rmdir()
        except OSError:
            break
    return True


def storage_bytes() -> int:
    blobs = OLLAMA_DIR / "models" / "blobs"
    return sum(f.stat().st_size for f in blobs.iterdir() if f.is_file()) if blobs.is_dir() else 0

