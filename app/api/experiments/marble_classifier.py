"""
Task fingerprinting on a finished agentic run: can the kind of task the agents worked on be
told from the encrypted traffic alone? This is the classifier side of the dataset's
analysis (the plots bundle's marble_top10_rf_feature_importance and
marble_topology_transfer_agent_visibility), run on the run's own captures.

Each capture becomes 247 measurements of its packets' timing, direction and size
(features_from_arrays, ported from marble-traffic-dataset's run_incremental_analysis.py).
A Random Forest then predicts the task category, always tested on tasks it has not seen:
the folds are split by task, so a task's repetitions are never on both sides.
  - within a topology, and across (trained on graph, tested on star's held-out tasks)
  - which measurements the forests rely on most (mean decrease in impurity)
  - with only some agents visible: the packets of k agents, chosen at random, for k = 1, 2, ...

It differs from the bundle where the bundle spends hours: the forests use its fixed
settings instead of a search per fold, importances come from the five fold forests instead
of fifty, three agent orderings instead of ten, and the sweep over random feature subsets
is left out.

numpy and scikit-learn are imported when first needed, so the API runs without them and
the results page says what is missing. The work runs in a background thread, one run at a
time and only while no run is capturing (a forest training on the host would change the
timings being captured), and its result is saved in the run's analysis folder.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import traceback
from importlib.util import find_spec
from pathlib import Path

from . import engine, marble_analysis
from .base import Link, Variant

VERSION = 1
FOLDS = 5              # as in the dataset's analysis
MIN_FOLDS = 3          # fewer tasks than this in a category: no classifier
TREES = 150
ORDERINGS = 3          # random agent orderings per capture for the visibility test
MAX_AGENTS = 4
TOP_FEATURES = 10
SEED = 2026
IDLE_THRESHOLD = marble_analysis.IDLE_THRESHOLD
SUMMARY_NAMES = ("mean", "std", "min", "q25", "median", "q75", "max")

_lock = threading.Lock()
_jobs: dict[str, dict] = {}        # run id → {"status", "step"} while its thread works
_turn = threading.Lock()           # one run's forests at a time


def missing() -> str | None:
    """Why the classifier can't run on this machine, if it can't."""
    absent = [package for module, package in (("numpy", "numpy"), ("sklearn", "scikit-learn")) if find_spec(module) is None]
    if absent:
        return (f"The classifier needs numpy and scikit-learn, and {' and '.join(absent)} {'is' if len(absent) == 1 else 'are'} "
                "not installed in the API's Python environment. Install them with: pip install -r api/requirements.txt")
    return None


# =============================================================================
# The 247 measurements of a capture
# =============================================================================


def _stats(np, values, prefix: str) -> dict[str, float]:
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return {f"{prefix}_{name}": 0.0 for name in SUMMARY_NAMES}
    return {
        f"{prefix}_mean": float(np.mean(values)),
        f"{prefix}_std": float(np.std(values)),
        f"{prefix}_min": float(np.min(values)),
        f"{prefix}_q25": float(np.quantile(values, 0.25)),
        f"{prefix}_median": float(np.median(values)),
        f"{prefix}_q75": float(np.quantile(values, 0.75)),
        f"{prefix}_max": float(np.max(values)),
    }


def features_from_arrays(absolute_times, directions, sizes) -> dict[str, float]:
    """The dataset's feature vector of a set of packets: their times, directions (1 to the
    service, -1 from it) and payload sizes. Kept line for line with the original."""
    import numpy as np

    absolute_times = np.asarray(absolute_times, float)
    directions = np.asarray(directions, int)
    sizes = np.asarray(sizes, float)
    order = np.argsort(absolute_times, kind="stable")
    timestamps = absolute_times[order] - absolute_times[order][0]
    directions, sizes = directions[order], sizes[order]
    incoming, outgoing = directions == -1, directions == 1
    duration = float(timestamps[-1]) if len(timestamps) > 1 else 0.0
    total_bytes = float(sizes.sum())
    in_bytes, out_bytes = float(sizes[incoming].sum()), float(sizes[outgoing].sum())
    f: dict[str, float] = {
        "total_packets": float(len(sizes)),
        "incoming_packets": float(incoming.sum()),
        "outgoing_packets": float(outgoing.sum()),
        "incoming_packet_fraction": float(incoming.mean()),
        "outgoing_packet_fraction": float(outgoing.mean()),
        "total_bytes": total_bytes,
        "incoming_bytes": in_bytes,
        "outgoing_bytes": out_bytes,
        "incoming_byte_fraction": in_bytes / max(total_bytes, 1.0),
        "outgoing_byte_fraction": out_bytes / max(total_bytes, 1.0),
        "incoming_outgoing_byte_ratio": in_bytes / max(out_bytes, 1.0),
        "task_duration": duration,
        "packets_per_second": len(sizes) / duration if duration else 0.0,
        "bytes_per_second": total_bytes / duration if duration else 0.0,
        "direction_changes": float(np.sum(np.diff(directions) != 0)),
    }
    for prefix, values in (
        ("packet_size", sizes),
        ("incoming_packet_size", sizes[incoming]),
        ("outgoing_packet_size", sizes[outgoing]),
        ("iat", np.diff(timestamps)),
        ("incoming_iat", np.diff(timestamps[incoming])),
        ("outgoing_iat", np.diff(timestamps[outgoing])),
    ):
        f.update(_stats(np, values, prefix))

    second = np.floor(timestamps).astype(int)
    f.update(_stats(np, np.bincount(second).astype(float), "one_second_packet_count"))
    f.update(_stats(np, np.bincount(second, weights=sizes).astype(float), "one_second_byte_count"))

    starts = np.r_[0, np.flatnonzero(np.diff(directions) != 0) + 1]
    ends = np.r_[starts[1:], len(directions)]
    burst_dir = directions[starts]
    burst_packets = (ends - starts).astype(float)
    burst_bytes = np.asarray([sizes[a:b].sum() for a, b in zip(starts, ends)])
    burst_duration = np.asarray([timestamps[b - 1] - timestamps[a] for a, b in zip(starts, ends)])
    f.update({
        "total_bursts": float(len(starts)),
        "incoming_bursts": float(np.sum(burst_dir == -1)),
        "outgoing_bursts": float(np.sum(burst_dir == 1)),
        "incoming_burst_fraction": float(np.mean(burst_dir == -1)),
        "outgoing_burst_fraction": float(np.mean(burst_dir == 1)),
    })
    for stem, values in (("burst_packets", burst_packets), ("burst_bytes", burst_bytes), ("burst_duration", burst_duration)):
        f.update(_stats(np, values, stem))
        f.update(_stats(np, values[burst_dir == -1], f"incoming_{stem}"))
        f.update(_stats(np, values[burst_dir == 1], f"outgoing_{stem}"))
    gaps = timestamps[starts[1:]] - timestamps[ends[:-1] - 1]
    f.update(_stats(np, gaps, "burst_gap"))

    iats = np.diff(timestamps)
    idle = iats[iats > IDLE_THRESHOLD]
    f.update({
        "idle_gap_count": float(len(idle)),
        "idle_time_total": float(idle.sum()),
        "idle_time_fraction": float(idle.sum() / duration) if duration else 0.0,
        "idle_gap_max": float(idle.max()) if len(idle) else 0.0,
    })
    episode_starts = np.r_[0, np.flatnonzero(iats > IDLE_THRESHOLD) + 1]
    episode_ends = np.r_[episode_starts[1:], len(timestamps)]
    episode_packets = (episode_ends - episode_starts).astype(float)
    episode_bytes = np.asarray([sizes[a:b].sum() for a, b in zip(episode_starts, episode_ends)])
    episode_duration = np.asarray([timestamps[b - 1] - timestamps[a] for a, b in zip(episode_starts, episode_ends)])
    episode_incoming = np.asarray([incoming[a:b].mean() for a, b in zip(episode_starts, episode_ends)])
    f["activity_episode_count"] = float(len(episode_starts))
    for stem, values in (("activity_episode_packets", episode_packets),
                         ("activity_episode_bytes", episode_bytes),
                         ("activity_episode_duration", episode_duration),
                         ("activity_episode_incoming_fraction", episode_incoming)):
        f.update(_stats(np, values, stem))

    section = np.minimum((timestamps / max(duration, 1e-12) * 20).astype(int), 19)
    packet_sections = np.bincount(section, minlength=20) / len(sizes)
    in_sections = np.bincount(section[incoming], weights=sizes[incoming], minlength=20) / max(in_bytes, 1.0)
    out_sections = np.bincount(section[outgoing], weights=sizes[outgoing], minlength=20) / max(out_bytes, 1.0)
    for index in range(20):
        f[f"progress_packet_fraction_{index + 1:02d}"] = float(packet_sections[index])
        f[f"progress_incoming_byte_fraction_{index + 1:02d}"] = float(in_sections[index])
        f[f"progress_outgoing_byte_fraction_{index + 1:02d}"] = float(out_sections[index])
    for label, selection in (("first30", slice(None, 30)), ("last30", slice(-30, None))):
        f[f"{label}_incoming_packets"] = float(incoming[selection].sum())
        f[f"{label}_outgoing_packets"] = float(outgoing[selection].sum())
        f[f"{label}_incoming_bytes"] = float(sizes[selection][incoming[selection]].sum())
        f[f"{label}_outgoing_bytes"] = float(sizes[selection][outgoing[selection]].sum())
    return f


# =============================================================================
# The run as a dataset
# =============================================================================


def _load(run_dir: Path, records: list[dict], link: Link, job: dict) -> list[dict]:
    """One row per completed capture with packets: its features, and its packets by agent."""
    import numpy as np

    done = [r for r in records if r.get("status") == "completed"]
    rows = []
    for n, record in enumerate(done):
        job["step"] = f"Measuring captures ({n + 1} of {len(done)})"
        stem = record["key"]
        try:
            packets, _ = marble_analysis.read_packets(run_dir / "captures" / f"{stem}.pcap", link)
        except (OSError, ValueError):
            continue
        if not packets:
            continue
        times = np.asarray([p[0] for p in packets], float)
        directions = np.asarray([p[1] for p in packets], int)
        sizes = np.asarray([p[2] for p in packets], float)
        assigned = np.asarray(marble_analysis.assign_agents(times.tolist(), marble_analysis._calls(run_dir, stem, link)), dtype=object)
        rows.append({
            "stem": stem, "number": n, "topology": record["variant"], "category": str(record["category"]),
            "group": int(record["prompt"]),
            "full": features_from_arrays(times, directions, sizes),
            "times": times, "directions": directions, "sizes": sizes, "assigned": assigned,
            "agents": sorted(set(assigned.tolist()) - {""}),
        })
    return rows


def _views(rows: list[dict], names: list[str], counts: int, job: dict):
    """For the visibility test: [capture, ordering, visible agents - 1] → feature vector, over
    the captures that have packets attributed to an agent. As in the dataset's analysis, an
    ordering is a random order of the capture's agents and k visible agents are its first k
    (all of them when the capture has fewer)."""
    import numpy as np

    kept = [r for r in rows if r["agents"]]
    views = np.zeros((len(kept), ORDERINGS, counts, len(names)))
    for i, row in enumerate(kept):
        job["step"] = f"Measuring partial views ({i + 1} of {len(kept)})"
        agents = np.asarray(row["agents"], dtype=object)
        for o in range(ORDERINGS):
            ordering = np.random.default_rng(42026 + 1009 * row["number"] + 7919 * o).permutation(agents)
            for k in range(1, counts + 1):
                visible = np.isin(row["assigned"], ordering[:min(k, agents.size)])
                f = features_from_arrays(row["times"][visible], row["directions"][visible], row["sizes"][visible])
                views[i, o, k - 1] = [f[name] for name in names]
    return kept, views


def _forest(seed: int):
    from sklearn.ensemble import RandomForestClassifier
    return RandomForestClassifier(n_estimators=TREES, class_weight="balanced", n_jobs=1, random_state=seed,
                                  max_features="sqrt", min_samples_leaf=2)


def _spread(values: list[float]) -> dict:
    import numpy as np
    return {"mean": float(np.mean(values)), "std": float(np.std(values)), "values": [float(v) for v in values]}


def _folds(rows: list[dict]) -> int:
    """Folds the run allows: every category needs a task in each one."""
    tasks: dict[str, set[int]] = {}
    for row in rows:
        tasks.setdefault(row["category"], set()).add(row["group"])
    return min(FOLDS, min((len(found) for found in tasks.values()), default=0))


def compute(run_dir: Path, records: list[dict], variants: list[Variant], link: Link, job: dict) -> dict:
    import numpy as np
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.model_selection import StratifiedGroupKFold

    started = time.monotonic()
    rows = _load(run_dir, records, link, job)
    categories = list(dict.fromkeys(r["category"] for r in rows))
    by_topology = {v.key: [r for r in rows if r["topology"] == v.key] for v in variants}
    by_topology = {key: found for key, found in by_topology.items() if found}
    labels = {v.key: v.label for v in variants}
    if len(categories) < 2:
        return {"status": "too_small", "reason": "A classifier needs completed tasks of at least two categories to tell apart."}
    folds = min((_folds(found) for found in by_topology.values()), default=0)
    if folds < MIN_FOLDS:
        return {"status": "too_small",
                "reason": f"A classifier is tested on tasks it has not seen, which takes at least {MIN_FOLDS} completed tasks "
                          f"in every category under every topology ({FOLDS} for the dataset's five folds)."}

    names = list(rows[0]["full"])
    X = {key: np.asarray([[r["full"][name] for name in names] for r in found]) for key, found in by_topology.items()}
    y = {key: np.asarray([r["category"] for r in found]) for key, found in by_topology.items()}
    groups = {key: np.asarray([r["group"] for r in found]) for key, found in by_topology.items()}

    def splits(target, group):
        # By task: a task's repetitions are all in training or all in the test
        return list(StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=SEED).split(target, target, groups=group))

    counts = min(MAX_AGENTS, max((len(r["agents"]) for r in rows), default=0))
    total = len(by_topology) * folds * (1 + ORDERINGS * counts)
    fitted = 0

    def fit(model, data, target):
        nonlocal fitted
        fitted += 1
        job["step"] = f"Training forests ({fitted} of {total})"
        return model.fit(data, target)

    # Within each topology, and from each to the others: the fold's forest is tested on the
    # held-out tasks of its own topology and on the same tasks under the other ones
    scores: dict[tuple[str, str], list[float]] = {}
    importances: dict[str, list] = {}
    for s, source in enumerate(by_topology):
        for fold, (train, test) in enumerate(splits(y[source], groups[source])):
            model = fit(_forest(100_000 + 25_000 * s + fold), X[source][train], y[source][train])
            importances.setdefault(source, []).append(model.feature_importances_)
            heldout = groups[source][test]
            for target in by_topology:
                tested = test if target == source else np.flatnonzero(np.isin(groups[target], heldout))
                if len(tested):
                    scores.setdefault((source, target), []).append(
                        balanced_accuracy_score(y[target][tested], model.predict(X[target][tested])))

    transfer = [
        {"train": source, "test": target, "train_label": labels[source], "test_label": labels[target],
         "within": source == target, **_spread(values)}
        for (source, target), values in scores.items()
    ]
    transfer.sort(key=lambda t: (not t["within"], list(by_topology).index(t["train"]), list(by_topology).index(t["test"])))

    importance = []
    for key, found in importances.items():
        matrix = np.asarray(found)
        top = np.argsort(matrix.mean(axis=0))[::-1][:TOP_FEATURES]
        importance.append({
            "key": key, "label": labels[key],
            "features": [{"name": names[i], "mean": float(matrix[:, i].mean()), "min": float(matrix[:, i].min()),
                          "max": float(matrix[:, i].max())} for i in top],
        })

    # With only some agents visible: every fold's forest is trained and tested on the same view
    visibility = []
    if counts:
        for t, (key, found) in enumerate(by_topology.items()):
            kept, views = _views(found, names, counts, job)
            if not kept or _folds(kept) < folds:
                continue
            target = np.asarray([r["category"] for r in kept])
            group = np.asarray([r["group"] for r in kept])
            shown = np.asarray([len(r["agents"]) for r in kept])
            per_count = []
            folded = splits(target, group)
            for k in range(1, counts + 1):
                by_fold = []
                for fold, (train, test) in enumerate(folded):
                    accuracy = []
                    for o in range(ORDERINGS):
                        model = fit(_forest(52_026 + 10_000 * t + 1000 * o + 100 * k + fold), views[train, o, k - 1], target[train])
                        accuracy.append(balanced_accuracy_score(target[test], model.predict(views[test, o, k - 1])))
                    by_fold.append(float(np.mean(accuracy)))
                per_count.append({"agents": k, "visible": float(np.minimum(shown, k).mean()), **_spread(by_fold)})
            visibility.append({"key": key, "label": labels[key], "captures": len(kept), "counts": per_count})

    return {
        "status": "ready",
        "categories": categories,
        "chance": 1 / len(categories),
        "folds": folds,
        "features": len(names),
        "trees": TREES,
        "orderings": ORDERINGS,
        "captures": {labels[key]: len(found) for key, found in by_topology.items()},
        "tasks": len({r["group"] for r in rows}),
        "transfer": transfer,
        "importance": importance,
        "visibility": visibility,
        "seconds": round(time.monotonic() - started, 1),
    }


# =============================================================================
# The background job and its saved result
# =============================================================================


def _key(run_dir: Path, records: list[dict]) -> str:
    """Changes when a capture or its result does."""
    parts = []
    for r in records:
        result = run_dir / "results" / f"{r['key']}.json"
        try:
            parts.append(f"{r['key']}:{r.get('status')}:{result.stat().st_mtime_ns}")
        except OSError:
            parts.append(f"{r['key']}:{r.get('status')}")
    return hashlib.sha1(f"{VERSION}|{'|'.join(parts)}".encode()).hexdigest()


def _work(run_id: str, run_dir: Path, records: list[dict], variants: list[Variant], link: Link, key: str, job: dict) -> None:
    try:
        # Never beside a capture: the forests would take the CPU its timings depend on. A queued
        # run is not capturing yet.
        while any(r.status in engine.RUNNING_STATUSES for r in engine.active_runs()):
            job.update(status="waiting", step="Waiting for the runs in progress to finish, so that training doesn't change their timings")
            time.sleep(10)
        job.update(status="waiting", step="Waiting for another run's classifier to finish")
        with _turn:
            job.update(status="computing", step="Starting")
            result = compute(run_dir, records, variants, link, job)
    except Exception as e:
        traceback.print_exc()
        result = {"status": "failed", "reason": f"{type(e).__name__}: {e}"}
    result.update(version=VERSION, key=key)
    try:
        cache = run_dir / "analysis" / "classifier.json"
        cache.parent.mkdir(exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(result))
        tmp.replace(cache)
    except OSError:
        pass   # the run was deleted meanwhile
    finally:
        with _lock:
            _jobs.pop(run_id, None)


def status(run, link: Link) -> dict:
    """The run's classifier results, or where they are: {"status": "ready", ...} once computed,
    otherwise "running" (the run is not over), "unavailable", "too_small", "failed",
    "waiting" or "computing" with a `step`."""
    if run.status in engine.ACTIVE_STATUSES:
        return {"status": "running", "reason": "The classifier is trained when the run has finished."}
    if problem := missing():
        return {"status": "unavailable", "reason": problem}
    records = marble_analysis.run_aggregate(run.id, run.run_dir, run.variants, link)["records"]
    key = _key(run.run_dir, records)
    try:
        cached = json.loads((run.run_dir / "analysis" / "classifier.json").read_text())
        if cached.get("version") == VERSION and cached.get("key") == key:
            return cached
    except (OSError, ValueError):
        pass
    with _lock:
        job = _jobs.get(run.id)
        if job is None:
            job = _jobs[run.id] = {"status": "computing", "step": "Starting"}
            threading.Thread(target=_work, args=(run.id, run.run_dir, records, list(run.variants), link, key, job),
                             name=f"classifier-{run.id}", daemon=True).start()
        return {"status": job["status"], "step": job["step"]}
