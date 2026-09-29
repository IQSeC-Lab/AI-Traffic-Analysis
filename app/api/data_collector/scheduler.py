"""
Where Data Collector runs go, and whether they can start now.

- A run has one or more workers. Each worker is its own model instance with its
  own packet capture; the workers share the run's prompts.
- Runs (and workers) on different GPUs run in parallel.
- A worker reserves its model's estimated GPU memory for the whole run: the model
  is reloaded for every prompt, so its real usage comes and goes between prompts,
  and nothing else should take that memory meanwhile.
- A run that doesn't fit waits in the queue until there is room for all its workers.
- CPU runs go one at a time; sharing the CPU would distort each other's timings.
"""

from __future__ import annotations

HEADROOM = 0.95   # never plan to fill a GPU past 95% of its memory

GpuRequest = list[int] | str   # "auto", or GPU indices ([] = CPU)


def _gb(mb: float) -> str:
    return f"{mb / 1024:.1f} GB"


def per_gpu_mb(need_mb: float, gpus: list[int]) -> float:
    """A model split across several GPUs needs its share on each."""
    return need_mb / max(1, len(gpus))


def free_mb(gpu: dict, reserved_mb: float) -> float:
    """Memory a new worker can plan on. nvidia-smi sees other processes and our loaded models;
    reservations cover our workers between prompts, when their model isn't loaded."""
    total = gpu.get("memory_total_mb")
    if total is None:   # memory unknown: allow one worker per GPU
        return float("inf") if reserved_mb == 0 else float("-inf")
    return total * HEADROOM - max(gpu.get("memory_used_mb") or 0, reserved_mb)


def check_possible(request: GpuRequest, need_mb: float, workers: int, gpus: list[dict]) -> None:
    """Raise ValueError when a run could never start, even on idle GPUs."""
    if request == []:
        return
    if not gpus:
        raise ValueError("No NVIDIA GPU detected on this host. Run on the CPU instead.")
    capacity = {g["index"]: (g["memory_total_mb"] or float("inf")) * HEADROOM for g in gpus}
    if request == "auto":
        if need_mb > max(capacity.values()):
            raise ValueError(
                f"The model needs about {_gb(need_mb)} of GPU memory, more than any single GPU has "
                f"({_gb(max(capacity.values()))}). Select several GPUs to split it."
            )
        fit = sum(int(cap // need_mb) if cap != float("inf") else 1 for cap in capacity.values())
        if workers > fit:
            raise ValueError(
                f"Only {fit} instance{'s' if fit != 1 else ''} of this model (about {_gb(need_mb)} each) "
                f"fit on your GPUs at once. Use {fit} worker{'s' if fit != 1 else ''} or fewer."
            )
        return
    missing = sorted(set(request) - set(capacity))
    if missing:
        raise ValueError(f"GPU(s) {missing} not found. Available: {sorted(capacity)}.")
    share = per_gpu_mb(need_mb * workers, request)
    too_small = [i for i in request if share > capacity[i]]
    if too_small:
        raise ValueError(
            f"{workers} worker{'s' if workers > 1 else ''} need about {_gb(share)} on each selected GPU; "
            f"GPU {too_small[0]} has {_gb(capacity[too_small[0]])}. Use fewer workers or more GPUs."
        )


def place(
    request: GpuRequest,
    need_mb: float,
    workers: int,
    gpus: list[dict],
    reserved: dict[int, float],
    cpu_busy: bool,
) -> tuple[list[list[int]] | None, str]:
    """The GPUs for each worker if the run can start now, otherwise (None, why it waits)."""
    if request == []:
        if cpu_busy:
            return None, "Waiting for the CPU run in progress to finish"
        return [[] for _ in range(workers)], ""

    if request == "auto":
        # Each worker goes to the GPU with the most room left, so workers spread out.
        room = {g["index"]: free_mb(g, reserved.get(g["index"], 0)) for g in gpus}
        placement = []
        for _ in range(workers):
            fits = [i for i, free in room.items() if free >= need_mb]
            if not fits:
                each = f" for each of {workers} instances" if workers > 1 else ""
                return None, f"Waiting for {_gb(need_mb)} of free memory on a GPU{each}"
            best = max(fits, key=room.get)
            room[best] -= need_mb
            placement.append([best])
        return placement, ""

    # Chosen GPUs: every worker splits its model across all of them.
    by_index = {g["index"]: g for g in gpus}
    share = per_gpu_mb(need_mb * workers, request)
    busy = [i for i in request if i not in by_index or free_mb(by_index[i], reserved.get(i, 0)) < share]
    if not busy:
        return [list(request) for _ in range(workers)], ""
    return None, f"Waiting for {_gb(share)} of free memory on GPU {', '.join(map(str, busy))}"
