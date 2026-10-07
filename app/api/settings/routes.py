"""HTTP endpoints for settings, mounted at /api/settings."""

from fastapi import APIRouter, HTTPException, Response
from huggingface_hub import HfApi
from huggingface_hub.errors import HfHubHTTPError
from pydantic import BaseModel, Field

import tempfile
from pathlib import Path

from experiments import engine
from storage import DATA_DIR, MODELS_DIR, OLLAMA_DIR, model_dir_name

from . import model_downloader, ollama_models, store
from .model_downloader import DownloadRequest

router = APIRouter(prefix="/settings", tags=["settings"])


class ResultsDirRequest(BaseModel):
    path: str = Field(..., min_length=1)


class TokenRequest(BaseModel):
    token: str = Field(..., min_length=1)


class OllamaPullRequest(BaseModel):
    model: str = Field(..., pattern=ollama_models.MODEL_PATTERN,
                       description="Name in the Ollama library, with its tag: llama3.2:3b")


class TemperatureRequest(BaseModel):
    temperature: float = Field(..., ge=0, le=2, description="0 is greedy decoding.")


def _token_status() -> dict:
    saved = store.load()
    token = store.hf_token()
    return {
        "set": token is not None,
        "source": "saved" if saved.get("hf_token") else ("env" if token else None),
        "hint": f"{token[:3]}…{token[-4:]}" if token else None,   # never return the token itself
        "username": saved.get("hf_username") if saved.get("hf_token") else None,
    }


def _settings() -> dict:
    return {
        "hf_token": _token_status(),
        "models_dir": str(MODELS_DIR),
        "results_dir": str(store.results_root()),
        "results_default": str(DATA_DIR),
        "results_dirs": [str(p) for p in store.results_roots()],
        "default_temperature": store.default_temperature(),
        "original_temperature": store.ORIGINAL_TEMPERATURE,
    }


@router.get("")
def get_settings() -> dict:
    return _settings()


@router.put("/results-dir")
def set_results_dir(req: ResultsDirRequest) -> dict:
    """Save new experiment results in this folder (on the machine running the API)."""
    path = Path(req.path.strip()).expanduser()
    if not path.is_absolute():
        raise HTTPException(400, "Use an absolute path, e.g. /data/mallm-results.")
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            pass
    except OSError as e:
        raise HTTPException(400, f"Can't write to {path}: {e.strerror or e}")
    store.set_results_root(path.resolve())
    return _settings()


@router.delete("/results-dir")
def reset_results_dir() -> dict:
    store.set_results_root(None)
    return _settings()


@router.put("/default-temperature")
def set_default_temperature(req: TemperatureRequest) -> dict:
    """The sampling temperature of new runs of every experiment except Temperature Change,
    which sets its own. Runs keep the temperature they started with."""
    store.update(default_temperature=round(req.temperature, 2))
    return _settings()


@router.delete("/default-temperature")
def reset_default_temperature() -> dict:
    """Back to 0.7, the temperature of the original scripts."""
    store.update(default_temperature=None)
    return _settings()


@router.put("/hf-token")
def save_hf_token(req: TokenRequest) -> dict:
    """Check the token with HuggingFace, then save it for model downloads."""
    token = req.token.strip()
    try:
        user = HfApi().whoami(token=token)
    except HfHubHTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            raise HTTPException(400, "HuggingFace rejected this token.")
        raise HTTPException(502, "Could not verify the token with HuggingFace.")
    except OSError:
        raise HTTPException(502, "Could not reach huggingface.co.")
    store.update(hf_token=token, hf_username=user.get("name"))
    return _token_status()


@router.delete("/hf-token")
def delete_hf_token() -> dict:
    store.update(hf_token=None, hf_username=None)
    return _token_status()


@router.get("/models")
def list_models() -> dict:
    return {
        "models_dir": str(MODELS_DIR),
        "models": model_downloader.list_models(),
        "downloads": [d.summary() for d in model_downloader.all_downloads()],
    }


@router.delete("/models/{folder}", status_code=204)
def delete_model(folder: str) -> Response:
    """Delete a downloaded model. Refused while it downloads or an active run uses it."""
    in_use = [r.id for r in engine.active_runs() if folder in map(model_dir_name, r.models)]
    if in_use:
        raise HTTPException(409, f"Run {in_use[0]} is using this model. Cancel it or wait for it to finish.")
    try:
        deleted = model_downloader.delete_model(folder)
    except model_downloader.ModelInUse as e:
        raise HTTPException(409, str(e))
    if not deleted:
        raise HTTPException(404, f"Model not found: {folder}")
    return Response(status_code=204)


@router.post("/models/download", status_code=202)
def download_model(req: DownloadRequest) -> dict:
    """Download a model in the background. Downloads run one at a time."""
    try:
        download = model_downloader.start(req)
    except (model_downloader.AlreadyDownloaded, model_downloader.DownloadConflict) as e:
        raise HTTPException(409, str(e))
    return download.summary()


# ── Ollama models (the agentic experiments, and the Data Collector on Ollama) ─

@router.get("/ollama-models")
def list_ollama_models() -> dict:
    return {
        "models_dir": str(OLLAMA_DIR),
        "models": ollama_models.list_models(),
        "downloads": [p.summary() for p in ollama_models.all_pulls()],
    }


@router.post("/ollama-models/download", status_code=202)
def download_ollama_model(req: OllamaPullRequest) -> dict:
    """Pull a model from the Ollama library in the background. Downloads run one at a time."""
    try:
        pulling = ollama_models.start(req.model)
    except (ollama_models.AlreadyPulled, ollama_models.PullConflict) as e:
        raise HTTPException(409, str(e))
    return pulling.summary()


@router.delete("/ollama-models/{model:path}", status_code=204)
def delete_ollama_model(model: str) -> Response:
    """Delete a pulled model. Refused while it downloads or an active run uses it."""
    name = ollama_models.normalize(model)
    in_use = [r.id for r in engine.active_runs() if name in {ollama_models.normalize(m) for m in r.models}]
    if in_use:
        raise HTTPException(409, f"Run {in_use[0]} is using this model. Cancel it or wait for it to finish.")
    try:
        deleted = ollama_models.delete(model)
    except ollama_models.ModelInUse as e:
        raise HTTPException(409, str(e))
    if not deleted:
        raise HTTPException(404, f"Model not found: {model}")
    return Response(status_code=204)
