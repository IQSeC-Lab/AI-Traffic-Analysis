"""
Thin wrapper around the docker CLI.

Commands are passed as argument lists and never through a shell, because
values such as the model name now come from HTTP requests.
"""

from __future__ import annotations

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


def must(*args: str, ctx: str) -> str:
    p = run(*args)
    if p.returncode != 0:
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
