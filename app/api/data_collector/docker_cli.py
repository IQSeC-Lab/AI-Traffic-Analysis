"""
Thin wrapper around the docker CLI.

Commands are passed as argument lists and never through a shell, because
values such as the model name now come from HTTP requests.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def run(*args: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", "docker: command not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"docker {args[0]}: timed out after {timeout}s")


def _disk_full_message(ctx: str) -> str:
    root = run("info", "--format", "{{.DockerRootDir}}", timeout=10).stdout.strip() or "/var/lib/docker"
    try:
        usage = shutil.disk_usage(root)
        space = f"{usage.free / 2**30:.1f} GB free of {usage.total / 2**30:.0f} GB"
    except OSError:   # e.g. Docker Desktop, where it lives inside a VM
        space = "free space unknown from here"
    return (
        f"{ctx} failed: Docker ran out of disk space. It stores images in {root} ({space}). "
        "The model image needs about 10 GB (torch with its CUDA libraries). "
        "See what uses the space with `docker system df`, then free some with `docker builder prune` "
        "or by removing unused images, or move Docker's data-root to a bigger disk "
        "(on Docker Desktop, raise the disk limit in Settings → Resources)."
    )


def must(*args: str, ctx: str) -> str:
    p = run(*args)
    if p.returncode != 0:
        output = (p.stderr + p.stdout).lower()
        if "no space left on device" in output:
            raise RuntimeError(_disk_full_message(ctx))
        if "address pool" in output:   # "could not find an available, non-overlapping IPv4 address pool"
            raise RuntimeError(
                f"{ctx} failed: Docker has no address range left for another network. Every worker gets "
                "its own network, so use fewer workers, or remove networks nobody uses (list them with "
                "`docker network ls`)."
            )
        raise RuntimeError(
            f"{ctx} failed (rc={p.returncode})\n"
            f"CMD : docker {' '.join(args)}\n"
            f"STDERR:\n{p.stderr}\n"
            f"STDOUT:\n{p.stdout}"
        )
    return p.stdout


def exists(kind: str, name: str) -> bool:
    """kind is 'image', 'network' or 'container'."""
    return run(kind, "inspect", name).returncode == 0


def rm_container(name: str) -> None:
    run("rm", "-f", name)


def base_image(dockerfile: Path) -> str:
    """The image named on the Dockerfile's FROM line."""
    for line in dockerfile.read_text().splitlines():
        if line.strip().upper().startswith("FROM "):
            return line.split()[1]
    raise ValueError(f"No FROM line in {dockerfile}")
