"""
Where Data Collector runs go, and whether they can start now.

- A run has one or more workers. Each worker is its own model instance with its
  own containers, network and packet capture; the run's prompts are divided
  evenly between them.
- Chosen GPUs: each worker runs on one of them, in turn (worker 1 on the first
  GPU, worker 2 on the second, ...), so 2 GPUs and 2 workers means one copy of
  the model on each GPU. With split=True every worker's model is split across
  all of them instead, for models too large for one GPU.
- Auto: each worker goes to the GPU with the fewest of the run's workers so far,
  then the most free memory, so workers spread over the GPUs.
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


def load_mb(worker_gpus: list[list[int]], need_mb: float) -> dict[int, float]:
    """GPU memory the workers need on each GPU."""
    load: dict[int, float] = {}
    for gpus in worker_gpus:
        for g in gpus:
            load[g] = load.get(g, 0) + per_gpu_mb(need_mb, gpus)
    return load


def chosen_worker_gpus(request: list[int], workers: int, split: bool) -> list[list[int]]:
    """The GPUs of each worker on chosen GPUs: all of them (split), or one each in turn."""
    if split:
        return [list(request) for _ in range(workers)]
    return [[request[k % len(request)]] for k in range(workers)]


def free_mb(gpu: dict, reserved_mb: float) -> float:
    """Memory a new worker can plan on. nvidia-smi sees other processes and our loaded models;
    reservations cover our workers between prompts, when their model isn't loaded."""
    total = gpu.get("memory_total_mb")
    if total is None:   # memory unknown: allow one worker per GPU
        return float("inf") if reserved_mb == 0 else float("-inf")
    return total * HEADROOM - max(gpu.get("memory_used_mb") or 0, reserved_mb)


def check_possible(request: GpuRequest, need_mb: float, workers: int, gpus: list[dict], split: bool = False) -> None:
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
                f"({_gb(max(capacity.values()))}). Choose several GPUs and split the model across them."
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
    worker_gpus = chosen_worker_gpus(request, workers, split)
    load = load_mb(worker_gpus, need_mb)
    too_small = [i for i in request if load.get(i, 0) > capacity[i]]
    if not too_small:
        return
    i = too_small[0]
    if not split and need_mb > capacity[i]:
        raise ValueError(
            f"The model needs about {_gb(need_mb)} of GPU memory, more than GPU {i} has ({_gb(capacity[i])}). "
            + ("Split the model across the selected GPUs instead." if len(request) > 1
               else "Select several GPUs and split the model across them.")
        )
    on_gpu = sum(i in g for g in worker_gpus)
    raise ValueError(
        f"{on_gpu} worker{'s' if on_gpu > 1 else ''} need about {_gb(load[i])} on GPU {i}, "
        f"which has {_gb(capacity[i])}. Use fewer workers or more GPUs."
    )


def place(
    request: GpuRequest,
    need_mb: float,
    workers: int,
    gpus: list[dict],
    reserved: dict[int, float],
    cpu_busy: bool,
    split: bool = False,
) -> tuple[list[list[int]] | None, str]:
    """The GPUs for each worker if the run can start now, otherwise (None, why it waits)."""
    if request == []:
        if cpu_busy:
            return None, "Waiting for the CPU run in progress to finish"
        return [[] for _ in range(workers)], ""

    if request == "auto":
        # Spread the workers: the GPU with the fewest of them first, then the one with the most room.
        room = {g["index"]: free_mb(g, reserved.get(g["index"], 0)) for g in gpus}
        count = dict.fromkeys(room, 0)
        placement = []
        for _ in range(workers):
            fits = [i for i, free in room.items() if free >= need_mb]
            if not fits:
                each = f" for each of {workers} instances" if workers > 1 else ""
                return None, f"Waiting for {_gb(need_mb)} of free memory on a GPU{each}"
            best = min(fits, key=lambda i: (count[i], -room[i]))
            room[best] -= need_mb
            count[best] += 1
            placement.append([best])
        return placement, ""

    by_index = {g["index"]: g for g in gpus}
    worker_gpus = chosen_worker_gpus(request, workers, split)
    load = load_mb(worker_gpus, need_mb)
    busy = [i for i in request if i not in by_index or free_mb(by_index[i], reserved.get(i, 0)) < load.get(i, 0)]
    if not busy:
        return worker_gpus, ""
    return None, "Waiting for free memory on " + ", ".join(f"GPU {i} ({_gb(load.get(i, 0))})" for i in busy)
