"""Host capabilities the experiments depend on: NVIDIA GPUs and Docker."""

import shutil
import subprocess

from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["system"])


def _int(value: str) -> int | None:
    try:
        return int(float(value))
    except ValueError:   # "[N/A]" on some GPUs
        return None


def detect_gpus() -> list[dict]:
    """NVIDIA GPUs on this host, via nvidia-smi. Empty when there are none."""
    if not shutil.which("nvidia-smi"):
        return []
    try:
        p = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if p.returncode != 0:
        return []
    gpus = []
    for line in p.stdout.splitlines():
        parts = [s.strip() for s in line.split(",")]
        if len(parts) < 5:
            continue
        gpus.append({
            "index": int(parts[0]),
            "name": ", ".join(parts[1:-3]),
            "memory_total_mb": _int(parts[-3]),
            "memory_used_mb": _int(parts[-2]),
            "utilization_pct": _int(parts[-1]),
        })
    return gpus


def docker_status() -> dict:
    try:
        p = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        return {"available": False, "version": None, "error": "Docker is not installed."}
    except subprocess.TimeoutExpired:
        return {"available": False, "version": None, "error": "Docker did not respond."}
    if p.returncode != 0:
        return {"available": False, "version": None, "error": "Docker is not running."}
    return {"available": True, "version": p.stdout.strip(), "error": None}


@router.get("")
def system_info() -> dict:
    return {"gpus": detect_gpus(), "docker": docker_status()}
