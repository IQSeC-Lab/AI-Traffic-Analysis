"""
The capture engine every experiment runs on, ported from 2-Data-Collector/main.py.

For each prompt (optionally repeated), once per variant of the experiment:
  1. Start a fresh inference container  (new conversation)
  2. Delay its outgoing traffic with tc netem, when the variant sets a network condition
  3. Start a tcpdump sidecar sharing its network namespace
  4. Send the prompt from a client container on the internal network
  5. Save the PCAP + logs and remove that capture's containers

A run can use several workers: each is its own model instance (typically one per
GPU) with its own containers, isolated network and packet capture, and the run's
captures are divided evenly between them. Several runs can be active at once, of
any experiment: runs on different GPUs run in parallel and the rest wait in one
shared queue until there is room (see scheduler.py). Each run has its own
container names and networks.

When a run ends (completed, failed or cancelled) every Docker resource it
created is removed: its containers, its networks and the llm-toolbox image it
built. Images the app had to pull (the base image, netshoot) are shared by
concurrent runs, so they are removed when the last active run ends.
Everything a run creates carries its experiment's label (Kind.run_label) set to
the run id, so cleanup never touches containers or images that belong to anything else.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import traceback
import uuid
from collections import Counter, deque
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from console import console
from prompt_library import store as prompt_library
from settings import store as settings_store
from storage import DATA_DIR, MODELS_DIR, estimate_gpu_memory_mb, has_weights, model_dir_name
from system import detect_gpus

from . import docker_cli as docker
from . import scheduler
from .base import PROMPTS_FILE, Kind, RunConfig, Variant
from .delay import netem_args
from .kinds import KINDS


# =============================================================================
# Configuration
# =============================================================================

TOOLBOX_DIR = Path(__file__).resolve().parent / "toolbox"   # docker build context
DOCKERFILE  = TOOLBOX_DIR / "Dockerfile.llmtool"

# Tagged per run and distinct from the standalone scripts' "llm-toolbox",
# so removing it never affects those scripts.
IMAGE_REPO     = "mallm-llm-toolbox"
NETSHOOT_IMAGE = "nicolaka/netshoot"   # tcpdump, and tc for the Delay experiment
# Images the app pulled and hasn't removed yet, shared by every experiment. Pulled
# images can't carry a run label, so this is how cleanup (and the orphan sweep after
# a crash) finds them.
PULLED_FILE    = DATA_DIR / ".pulled-images.json"
# Next run number (#1, #2, ...), shared by every experiment. Numbers are never reused,
# so a number always means the same run.
COUNTER_FILE   = DATA_DIR / ".next-run-number"
# Where both lived when the Data Collector was the only experiment
LEGACY_PULLED_FILE  = DATA_DIR / "data-collector" / ".pulled-images.json"
LEGACY_COUNTER_FILE = DATA_DIR / "data-collector" / ".next-run-number"
INFERENCE_PORT = 8000
PCAP_FLUSH_SECONDS = 5
LOG_TAIL       = 2000
SCHEDULE_EVERY = 5   # seconds between queue checks (GPU memory can free up at any time)

RUNNING_STATUSES = {"running", "cancelling", "cleaning_up"}
ACTIVE_STATUSES  = RUNNING_STATUSES | {"queued"}
RUN_FILE = "run.json"   # the run's summary, so history survives API restarts
RUN_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


class FatalRunError(RuntimeError):
    """A capture failure that every later capture would repeat too, so the run stops."""


def _runs_dir(kind: Kind) -> Path:
    """Where new runs of an experiment are saved (Settings → Storage)."""
    return settings_store.results_root() / kind.slug


def _all_runs_dirs(kind: Kind) -> list[Path]:
    """Every folder runs were saved in, so they stay listed after the results folder changes."""
    return [root / kind.slug for root in settings_store.results_roots()]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _gpu_args(gpus: list[int]) -> list[str]:
    if not gpus:
        return []
    devices = ",".join(str(g) for g in gpus)
    # Docker needs several devices quoted inside the value: --gpus '"device=0,1"'
    return ["--gpus", f'"device={devices}"' if len(gpus) > 1 else f"device={devices}"]


def deal(units: list[tuple], workers: int) -> list[list[tuple]]:
    """
    Each worker's units (variant, prompt, iteration, index), in run order.

    Every variant's captures are dealt out over the workers in turn (1, 3, 5 / 2, 4, 6),
    starting one worker further along for each variant. So each variant, and each
    prompt category, runs on every GPU instead of one variant landing on one GPU, and
    the variants of one prompt run side by side on different workers.
    """
    shares: list[list[tuple]] = [[] for _ in range(workers)]
    dealt: Counter = Counter()
    for unit in units:
        v = unit[0]
        shares[(dealt[v] + v) % workers].append(unit)
        dealt[v] += 1
    return shares


# ── Images pulled by the app, shared by concurrent runs ──────────────────────

def _pulled_images() -> list[str]:
    images: list[str] = []
    for path in (PULLED_FILE, LEGACY_PULLED_FILE):
        try:
            images += json.loads(path.read_text())
        except (OSError, ValueError):
            pass
    return sorted(set(images))


def _set_pulled_images(images: list[str]) -> None:
    if images:
        PULLED_FILE.parent.mkdir(parents=True, exist_ok=True)
        PULLED_FILE.write_text(json.dumps(sorted(set(images))))
    else:
        PULLED_FILE.unlink(missing_ok=True)
    LEGACY_PULLED_FILE.unlink(missing_ok=True)   # merged into PULLED_FILE by _pulled_images()


# =============================================================================
# Experiment
# =============================================================================


class Experiment:
    def __init__(self, kind: Kind, config: RunConfig, variants: list[Variant], prompts: dict[int, dict],
                 need_mb: int, number: int):
        self.kind   = kind
        self.id     = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.number = number                      # #1, #2, ... shown as the run's identifier
        self.name   = (config.name or "").strip() or None
        self.config = config
        self.variants = variants
        self.models = list(dict.fromkeys(v.model for v in variants))
        self.status = "queued"
        self.step: str | None = None              # run-wide step (setup, cleanup); workers keep their own
        self.error: str | None = None
        self.cleanup: dict | None = None
        self.created_at  = _now()
        self.started_at: str | None = None
        self.finished_at: str | None = None

        # Scheduling
        self.need_mb = need_mb                    # estimated GPU memory per worker (0 on CPU)
        self.worker_gpus: list[list[int]] | None = None   # GPUs of each worker, once started
        self._workers: list[dict] = []            # per worker: gpus, network, progress, current prompt, step
        self._shares: list[list[tuple]] = []      # each worker's captures, fixed when the run starts
        self.queue_position: int | None = None
        self.queue_reason: str | None = None

        self.image        = f"{IMAGE_REPO}:{self.id}"
        self.label        = f"{kind.run_label}={self.id}"
        self.run_dir      = _runs_dir(kind) / self.id
        self.captures_dir = self.run_dir / "captures"
        self.logs_dir     = self.run_dir / "logs"
        self.results_dir  = self.run_dir / "results"   # client output: response + per-event timing
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Fixed when the run is created, so editing prompts mid-run (or later) doesn't change it
        self.prompts = prompts
        self.prompt_numbers = list(prompts)
        (self.run_dir / PROMPTS_FILE).write_text(json.dumps(prompts, indent=1))
        self.total     = len(self.prompt_numbers) * (config.repeat or 1) * len(variants)
        self.completed = 0
        self._done_by_variant: Counter = Counter()

        self._released_shared = False   # set once this run no longer needs the shared pulled images
        self._state_lock = threading.Lock()     # workers update progress, logs and run.json concurrently
        self._local = threading.local()         # which worker the current thread is
        self._log_tail: deque[tuple[int, str]] = deque(maxlen=LOG_TAIL)
        self._log_seq = 0
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"{kind.slug}-{self.id}", daemon=True)

    # ── Public ───────────────────────────────────────────────────────────────

    def start(self, worker_gpus: list[list[int]]) -> None:
        """Called by the scheduler once there is room for all the run's workers."""
        self.worker_gpus = worker_gpus
        n = len(worker_gpus)
        self._shares = deal(list(self._units()), n)
        self._workers = [
            {
                "gpus": gpus,
                # Its own isolated network, so no worker's traffic reaches another's capture
                "network": f"mallm-{self.id}" if n == 1 else f"mallm-{self.id}-w{k + 1}",
                "done": 0,
                "total": len(share),
                "current": None,
                "step": None,
            }
            for k, (gpus, share) in enumerate(zip(worker_gpus, self._shares))
        ]
        self.queue_position = self.queue_reason = None
        self.started_at = _now()
        self.status = "running"
        self._save()
        self._thread.start()

    def cancel(self) -> None:
        if self.status == "queued":
            self._cancel.set()
            self.status = "cancelled"
            self.finished_at = _now()
            self.queue_position = self.queue_reason = None
            self._save()
            self.log("[experiment] Cancelled before it started.")
            _wake.set()
            return
        if self.status not in RUNNING_STATUSES or self._cancel.is_set():
            return
        self._cancel.set()
        self.status = "cancelling"
        self._save()
        self.log("[experiment] Cancel requested, stopping containers...")
        threading.Thread(target=self._stop_containers_until_cleanup, daemon=True).start()

    def rename(self, name: str | None) -> None:
        self.name = name
        self._save()

    def join(self, timeout: float | None = None) -> None:
        if self._thread.is_alive():
            self._thread.join(timeout)

    def logs_after(self, after: int) -> dict:
        """Log lines newer than sequence number `after`, for live tailing."""
        lines = [line for seq, line in list(self._log_tail) if seq > after]
        return {"lines": lines, "next": self._log_seq}

    @property
    def assigned_gpus(self) -> list[int] | None:
        if self.worker_gpus is None:
            return None
        return sorted({g for gpus in self.worker_gpus for g in gpus})

    def summary(self) -> dict:
        pcaps = list(self.captures_dir.glob("*.pcap")) if self.captures_dir.exists() else []
        busy = next((w for w in self._workers if w["current"]), None)
        per_variant = len(self.prompt_numbers) * (self.config.repeat or 1)
        return {
            "id": self.id,
            "number": self.number,
            "name": self.name,
            "experiment": self.kind.slug,
            "status": self.status,
            # Run-wide step (setup, cleanup), else the first busy worker's
            "step": self.step or (busy or {}).get("step"),
            "current": (busy or {}).get("current"),
            "workers": [dict(w) for w in self._workers],
            # Prompt texts given to the run are in its prompts.json, not in every summary
            "config": self.config.model_dump(exclude={"name", "prompt_texts"}),
            "models": self.models,
            "variants": [
                {**v.as_dict(), "done": self._done_by_variant[v.key], "total": per_variant} for v in self.variants
            ],
            "assigned_gpus": self.assigned_gpus,
            "gpu_memory_mb": self.need_mb or None,
            "queue": {"position": self.queue_position, "reason": self.queue_reason} if self.status == "queued" else None,
            "progress": {"completed": self.completed, "total": self.total},
            "prompt_count": len(self.prompt_numbers),
            "outputs": {"pcaps": len(pcaps), "pcap_bytes": sum(f.stat().st_size for f in pcaps)},
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "output_dir": str(self.run_dir),
            "cleanup": self.cleanup,
        }

    def _save(self) -> None:
        with self._state_lock:
            (self.run_dir / RUN_FILE).write_text(json.dumps(self.summary(), indent=2))

    def log(self, msg: str) -> None:
        msg = getattr(self._local, "tag", "") + msg   # "[w2] " inside a worker when there are several
        line = f"{datetime.now():%H:%M:%S} {msg}"
        with self._state_lock:
            self._log_seq += 1
            self._log_tail.append((self._log_seq, line))
            with (self.run_dir / "run.log").open("a") as f:
                f.write(line + "\n")
        console(msg)   # after run.log: the run keeps its log even when the console is gone

    def _set_step(self, step: str | None) -> None:
        """The step of the current worker, or of the whole run outside the workers."""
        worker = getattr(self._local, "worker", None)
        if worker is None:
            self.step = step
        else:
            self._workers[worker]["step"] = step

    # ── Main loop ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        self.log("=" * 60)
        self.log(f"LLM Traffic Capture · {self.kind.title} · run {self.id}")
        if len(self.models) == 1:
            self.log(f"Model   : {self.models[0]}")
        else:
            self.log(f"Models  : {', '.join(self.models)}")
        if self.kind.variable and self.kind.variable != "Model":
            self.log(f"Compare : {' · '.join(v.label for v in self.variants)}")
        temperatures = {v.temperature for v in self.variants}
        if len(temperatures) == 1:   # not a temperature sweep
            t = temperatures.pop()
            self.log(f"Sampling: {'greedy (temperature 0)' if t == 0 else f'temperature {t:g}'}")
        where = lambda gpus: " ".join(_gpu_args(gpus)[1:]) or "none (CPU)"
        if len(self._workers) == 1:
            self.log(f"Network : {self._workers[0]['network']}  (--internal bridge, no internet routing)")
            self.log(f"GPU     : {where(self._workers[0]['gpus'])}")
        else:
            self.log(f"Workers : {len(self._workers)}, captures divided between them, each on its own "
                     "--internal network (no internet routing)")
            for k, w in enumerate(self._workers):
                self.log(f"  w{k + 1}: GPU {where(w['gpus'])} · {w['total']} captures · network {w['network']}")
        self.log(f"Captures: {self.total}")
        self.log(f"Output  : {self.run_dir}")
        self.log("=" * 60)
        try:
            self._setup()
            self.step = None
            workers = [
                threading.Thread(target=self._work, args=(k,), name=f"{self.id}-w{k + 1}", daemon=True)
                for k in range(len(self._workers))
            ]
            for w in workers:
                w.start()
            for w in workers:
                w.join()
        except Exception as e:
            self.error = str(e)
            self.log(f"[experiment] ERROR: {e}")
            self.log(traceback.format_exc())
        finally:
            self.status = "cleaning_up"
            for w in self._workers:
                w["current"] = w["step"] = None
            self._save()
            self.step = "Removing Docker containers, network and images"
            self.cleanup = self._cleanup()
            self.step = None
            self.finished_at = _now()
            if self.error:
                self.status = "failed"
            elif self._cancel.is_set():
                self.status = "cancelled"
            else:
                self.status = "completed"
            self._save()
            self.log("=" * 60)
            self.log(f"✓ Experiment {self.status} ({self.completed}/{self.total})")
            self.log("=" * 60)
            _wake.set()   # its GPU is free: start whatever was waiting for it

    def _work(self, k: int) -> None:
        """Run worker k's share of the captures."""
        self._local.worker = k
        self._local.tag = f"[w{k + 1}] " if len(self._workers) > 1 else ""
        state = self._workers[k]
        try:
            for v, prompt_no, iteration, index in self._shares[k]:
                if self._cancel.is_set():
                    break
                variant = self.variants[v]
                state["current"] = {"prompt": prompt_no, "iteration": iteration, "index": index, "variant": variant.key}
                self._save()
                title = f"Prompt #{prompt_no:02d}"
                if iteration is not None:
                    title += f", iteration {iteration}/{self.config.repeat}"
                self.log("=" * 60)
                self.log(f"{title} · {variant.label if self.kind.variable else variant.model}")
                self.log("=" * 60)
                self._run_prompt(k, variant, self.prompts[prompt_no]["text"], index)
                if not self._cancel.is_set():
                    with self._state_lock:
                        self.completed += 1
                        state["done"] += 1
                        self._done_by_variant[variant.key] += 1
                    self._save()
        except Exception as e:   # a worker failing stops the run; its prompt errors are logged in _run_prompt
            self.error = str(e)
            self.log(f"[experiment] ERROR: {e}")
            self.log(traceback.format_exc())
            self._cancel.set()
        finally:
            state["current"] = state["step"] = None

    def _units(self):
        """
        Yield (variant, prompt number, iteration, file index) in run order. The variants
        of each prompt (and repetition) follow each other, so they are captured under the
        same conditions over the run, and a cancelled run still has all of them.
        """
        for n in self.prompt_numbers:
            iterations = [None] if self.config.repeat is None else range(1, self.config.repeat + 1)
            for it in iterations:
                # Composite index keeps every iteration's files distinct (same as main.py -p/-r)
                index = n if it is None else n * 1000 + it
                for v in range(len(self.variants)):
                    yield v, n, it, index

    # ── Setup ────────────────────────────────────────────────────────────────

    def _setup(self) -> None:
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Images that aren't on the host yet will be pulled by the app, so it removes them later.
        with _lock:
            new = [img for img in (docker.base_image(DOCKERFILE), NETSHOOT_IMAGE) if not docker.exists("image", img)]
            _set_pulled_images(_pulled_images() + new)

        self._set_step("Building Docker image")
        self.log(f"[setup] Building {self.image} Docker image...")
        docker.must(
            "build", "-t", self.image, "--label", self.label,
            "-f", str(DOCKERFILE), str(TOOLBOX_DIR),
            ctx="docker build llm-toolbox",
        )
        self._set_step("Pulling tcpdump image")
        docker.run("pull", NETSHOOT_IMAGE)
        self.log("[setup] ✓ Images ready.")

        self._set_step("Preparing network" + ("s" if len(self._workers) > 1 else ""))
        for w in self._workers:
            docker.must(
                "network", "create", "--driver", "bridge", "--internal",
                "--label", self.label, w["network"],
                ctx=f"create network {w['network']}",
            )
            self.log(f"[setup] ✓ Created isolated network: {w['network']}")

    # ── Per-prompt experiment ────────────────────────────────────────────────

    def _run_prompt(self, k: int, variant: Variant, prompt: str, index: int) -> None:
        stem          = f"{variant.key}-p{index:02d}"
        inf_container = None
        tc_cname      = None
        response      = None
        try:
            self._set_step("Starting inference server")
            inf_container = self._start_inference(k, variant)
            if self._cancel.is_set():
                return
            if variant.network:
                self._set_step("Adding network delay")
                self._apply_network(k, inf_container, variant.network)
                if self._cancel.is_set():
                    return
            self._set_step("Starting packet capture")
            tc_cname = self._start_capture(k, inf_container, stem)
            if self._cancel.is_set():
                return
            self._set_step("Loading model and streaming the response")
            response = self._send_prompt(k, variant, inf_container, prompt, index, stem)
            self._set_step("Flushing capture")
            self._cancel.wait(PCAP_FLUSH_SECONDS)   # let tcpdump flush remaining packets
        except FatalRunError:
            raise
        except Exception as e:
            self.log(f"[experiment] ERROR on prompt #{index}: {e}")
            self.log(traceback.format_exc())
        finally:
            self._set_step("Saving logs and PCAP")
            if inf_container:
                self._collect_logs(inf_container, variant, index, stem, prompt, response)
                docker.rm_container(inf_container)
            if tc_cname:
                self._stop_capture(tc_cname)

            pcap = self.captures_dir / f"{stem}.pcap"
            if pcap.exists():
                size_mb = pcap.stat().st_size / 1024 / 1024
                self.log(f"[capture] ✓ PCAP → {pcap} ({size_mb:.2f} MB)")
            else:
                self.log(f"[capture] ⚠ PCAP not found for prompt #{index}")

    def _start_inference(self, k: int, variant: Variant) -> str:
        cname = f"mallm-{self.id}-w{k + 1}-llm"
        docker.rm_container(cname)
        sampling = [] if variant.temperature is None else ["--temperature", str(variant.temperature)]
        docker.must(
            "run", "-d", "--name", cname, "--label", self.label,
            "--network", self._workers[k]["network"],
            *_gpu_args(self._workers[k]["gpus"]),
            "-v", f"{MODELS_DIR}:/models:ro",
            "-e", "HF_HUB_OFFLINE=1",
            "-e", "TRANSFORMERS_OFFLINE=1",
            "--shm-size", "2g",
            self.image, "python", "/app/inference_server.py",
            "--model-name", variant.model,
            "--model-path", f"/models/{model_dir_name(variant.model)}",
            *sampling,
            ctx="start inference server",
        )
        self.log(f"[inference] ✓ Container started: {cname}")
        return cname

    def _apply_network(self, k: int, inf_container: str, network: dict) -> None:
        """Delay the inference container's egress traffic with tc netem, from a transient
        netshoot sidecar sharing its network namespace (as in 6-Delay/main.py)."""
        cname = f"mallm-{self.id}-w{k + 1}-netem"
        docker.rm_container(cname)
        args = netem_args(network)
        p = docker.run(
            "run", "--rm", "--name", cname, "--label", self.label,
            "--network", f"container:{inf_container}",
            "--cap-add=NET_ADMIN",
            NETSHOOT_IMAGE, "tc", "qdisc", "add", "dev", "eth0", "root", "netem", *args,
        )
        if p.returncode == 0:
            self.log(f"[network] ✓ netem {' '.join(args)} on {inf_container}")
            return
        error = (p.stderr or p.stdout).strip()
        running = docker.run("inspect", "-f", "{{.State.Running}}", inf_container).stdout.strip() == "true"
        if not running:   # the server died on its own; the next capture may well work
            raise RuntimeError(f"Inference server stopped before the delay could be added: {error}")
        # tc itself failed, and would for every capture
        raise FatalRunError(
            f"Could not add the network delay with tc netem: {error}. The host kernel needs the "
            "sch_netem module; load it with `sudo modprobe sch_netem` and start the run again."
        )

    def _start_capture(self, k: int, inf_container: str, stem: str) -> str:
        tc_cname  = f"mallm-{self.id}-w{k + 1}-tcpdump"
        pcap_name = f"{stem}.pcap"
        docker.rm_container(tc_cname)
        time.sleep(2)
        p = docker.run(
            "run", "-d", "--name", tc_cname, "--label", self.label,
            "--network", f"container:{inf_container}",
            "-v", f"{self.captures_dir}:/captures",
            "--cap-add=NET_RAW", "--cap-add=NET_ADMIN",
            NETSHOOT_IMAGE, "tcpdump", "-i", "eth0", "-s0", "-U", "-w", f"/captures/{pcap_name}",
        )
        if p.returncode != 0:
            self.log(f"[capture] Failed to start sidecar: {p.stderr.strip()}")
            return tc_cname
        time.sleep(2)
        logs = docker.run("logs", tc_cname)
        if "listening on" in (logs.stdout + logs.stderr).lower():
            self.log(f"[capture] ✓ Sidecar active → {pcap_name}")
        else:
            self.log(f"[capture] ⚠ tcpdump status unclear: {(logs.stdout + logs.stderr)[:200]}")
        return tc_cname

    def _stop_capture(self, tc_cname: str) -> None:
        docker.run("stop", tc_cname)
        time.sleep(1)
        docker.rm_container(tc_cname)

    def _send_prompt(self, k: int, variant: Variant, inf_container: str, prompt: str, index: int, stem: str) -> str | None:
        """
        Write the prompt to a file, mount it into a client container, and
        reach the inference server by container-name DNS inside the network.
        """
        cname = f"mallm-{self.id}-w{k + 1}-client"
        prompt_file = self.logs_dir / f"prompt_{index:02d}.txt"
        # Workers on other variants may be sending the same prompt right now: replace the
        # file in one step so no client ever reads it half written.
        tmp = prompt_file.with_name(f".{prompt_file.name}.w{k + 1}")
        tmp.write_text(prompt)
        os.replace(tmp, prompt_file)
        docker.rm_container(cname)

        self.log(f"[client] Sending prompt #{index}...")
        p = docker.run(
            "run", "--rm", "--name", cname, "--label", self.label,
            "--network", self._workers[k]["network"],
            "-v", f"{self.logs_dir}:/prompts:ro",
            self.image, "python", "/app/client.py",
            "--host", inf_container,
            "--port", str(INFERENCE_PORT),
            "--index", str(index),
            "--max-tokens", str(self.config.max_tokens),
            "--prompt-file", f"/prompts/{prompt_file.name}",
        )
        if p.returncode != 0:
            self.log(f"[client] Error on prompt #{index}: {p.stderr.strip()[:300]}")
            return None
        try:
            # Last JSON line is the result printed by client.py
            last_json_line = [l for l in p.stdout.strip().splitlines() if l.startswith("{")][-1]
            result = json.loads(last_json_line)
            worker = self._workers[k]
            current = worker["current"]
            (self.results_dir / f"{stem}.json").write_text(json.dumps({
                **current,
                "category": self.prompts[current["prompt"]]["category"],
                "model": variant.model,
                "temperature": variant.temperature,
                **variant.columns,
                "worker": k + 1,
                "gpus": worker["gpus"],
                **result,
            }))
            self.log(f"[client] ✓ Prompt #{index} response received")
            return result.get("response")
        except Exception:
            self.log(f"[client] Could not parse client output: {p.stdout[:300]}")
            return None

    def _collect_logs(self, inf_container: str, variant: Variant, index: int, stem: str,
                      prompt: str | None = None, response: str | None = None) -> None:
        p = docker.run("logs", inf_container)
        log_path = self.logs_dir / f"{stem}.log"
        with log_path.open("w") as f:
            f.write("=" * 60 + "\n")
            f.write(f"PROMPT #{index}\n")
            if self.kind.variable:
                f.write(f"{self.kind.variable.upper()}: {variant.label}\n")
            f.write("=" * 60 + "\n")
            f.write(f"INPUT:\n{prompt or 'N/A'}\n\n")
            f.write(f"OUTPUT:\n{response or 'N/A'}\n")
            f.write("=" * 60 + "\n")
            f.write("SERVER LOGS:\n")
            f.write("=" * 60 + "\n")
            f.write(p.stdout if p.returncode == 0 else f"(log collection failed: {p.stderr.strip()})")
        self.log(f"[logs] Saved → {log_path}")

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _container_names(self) -> list[str]:
        p = docker.run("ps", "-a", "--filter", f"label={self.label}", "--format", "{{.Names}}")
        return p.stdout.split()

    def _stop_containers_until_cleanup(self) -> None:
        # Blocking calls (e.g. the client waiting on the model) only return once
        # their containers are gone, so keep removing them until cleanup starts.
        while self._thread.is_alive() and self.status == "cancelling":
            for name in self._container_names():
                docker.rm_container(name)
            self._thread.join(timeout=2)

    def _cleanup(self) -> dict:
        """Remove every Docker resource this run created. Never raises."""
        self.log("[cleanup] Removing Docker resources created by this run...")
        report: dict = {"containers": [], "networks": [], "images": [], "errors": []}

        def remove(what: str, *args: str) -> bool:
            p = docker.run(*args)
            if p.returncode != 0:
                report["errors"].append(f"{what}: {p.stderr.strip()}")
                self.log(f"[cleanup] ⚠ Could not remove {what}: {p.stderr.strip()}")
            return p.returncode == 0

        try:
            for name in self._container_names():
                if remove(f"container {name}", "rm", "-f", name):
                    report["containers"].append(name)

            networks = docker.run("network", "ls", "--filter", f"label={self.label}", "--format", "{{.Name}}")
            for net in networks.stdout.split():
                if remove(f"network {net}", "network", "rm", net):
                    report["networks"].append(net)

            # Our image first: a base image can't be removed while an image built on it exists.
            if docker.exists("image", self.image) and remove(f"image {self.image}", "image", "rm", self.image):
                report["images"].append(self.image)

            # Pulled images are shared: the last run to finish removes them.
            with _lock:
                self._released_shared = True
                last = not any(
                    r.status in RUNNING_STATUSES and not r._released_shared for r in _runs.values()
                )
                pulled = _pulled_images() if last else []
                if last:
                    _set_pulled_images([])
            for image in pulled:
                if docker.exists("image", image) and remove(f"image {image}", "image", "rm", image):
                    report["images"].append(image)
            if not last and _pulled_images():
                self.log("[cleanup] Shared images are kept until the other active runs finish.")
        except Exception as e:
            report["errors"].append(str(e))
            self.log(f"[cleanup] ⚠ {e}")

        self.log(
            f"[cleanup] ✓ Removed {len(report['containers'])} container(s), "
            f"networks: {', '.join(report['networks']) or 'none'}, "
            f"images: {', '.join(report['images']) or 'none'}"
        )
        return report


# =============================================================================
# Registry and scheduler, shared by every experiment
# =============================================================================

_runs: dict[str, Experiment] = {}
_lock = threading.RLock()
_wake = threading.Event()
_scheduler: threading.Thread | None = None


class RunConflict(Exception):
    pass


def _library_prompts(config: RunConfig) -> dict[int, dict]:
    """The prompts of a run that takes them from the prompt library: those chosen, or all."""
    numbers = [p["number"] for p in prompt_library.all_prompts()]
    invalid = [n for n in config.prompts or [] if n not in numbers]
    if invalid:
        raise ValueError(f"Unknown prompt number(s) {invalid}. See the prompt library.")
    return prompt_library.snapshot(config.prompts or numbers)


def with_default_temperature(variants: list[Variant]) -> list[Variant]:
    """Variants that don't set a temperature get the default from Settings. Fixed when the run
    is created, so it is recorded with the run and changing the setting never alters a run."""
    default = settings_store.default_temperature()
    return [
        # Also a column of the metrics CSV, like the temperatures of a Temperature Change run
        v if v.temperature is not None else replace(v, temperature=default, columns={**v.columns, "temperature": default})
        for v in variants
    ]


def submit(kind: Kind, config: RunConfig) -> Experiment:
    """Queue a run. It starts right away when its hardware is free, otherwise when it frees up."""
    prompts = (kind.prompts or _library_prompts)(config)
    variants = with_default_temperature(kind.variants(config))
    need_mb = 0
    for model in dict.fromkeys(v.model for v in variants):
        model_dir = MODELS_DIR / model_dir_name(model)
        if model_dir.resolve().parent != MODELS_DIR:
            raise ValueError(f"Invalid model: {model}")
        if not model_dir.exists():
            raise ValueError(f"Model not downloaded: {model} (expected {model_dir})")
        if not has_weights(model_dir):
            raise ValueError(f"Model directory has no weight files: {model_dir}. Download it again.")
        # Workers run the models one after the other, so they reserve room for the largest
        if config.gpus != []:
            need_mb = max(need_mb, estimate_gpu_memory_mb(model_dir))

    if isinstance(config.gpus, list):
        config.gpus = sorted(set(config.gpus))
    if config.workers is None:   # one copy of the model per chosen GPU
        per_gpu = isinstance(config.gpus, list) and config.gpus and not config.split_model
        config.workers = len(config.gpus) if per_gpu else 1
    # A worker without captures would only hold on to GPU memory
    captures = len(prompts) * (config.repeat or 1) * len(variants)
    config.workers = min(config.workers, captures)

    gpus = detect_gpus() if config.gpus != [] else []
    scheduler.check_possible(config.gpus, need_mb, config.workers, gpus, config.split_model)

    with _lock:
        run = Experiment(kind, config, variants, prompts, need_mb, _next_number())
        _runs[run.id] = run
        run._save()
    _ensure_scheduler()
    _schedule()   # start now if it fits, so the response already says "running"
    return run


def _schedule() -> None:
    """Start every queued run whose hardware has room, oldest first, whatever its experiment."""
    with _lock:
        queued = sorted((r for r in _runs.values() if r.status == "queued"), key=lambda r: r.id)
        if not queued:
            return
        running = [r for r in _runs.values() if r.status in RUNNING_STATUSES]
        gpus = detect_gpus() if any(r.config.gpus != [] for r in queued) else []
        reserved: dict[int, float] = {}

        def reserve(run: Experiment, worker_gpus: list[list[int]]) -> None:
            for g, mb in scheduler.load_mb(worker_gpus, run.need_mb).items():
                reserved[g] = reserved.get(g, 0) + mb

        for r in running:
            reserve(r, r.worker_gpus or [])
        cpu_busy = any(r.config.gpus == [] for r in running)

        position = 0
        for run in queued:
            placed, reason = scheduler.place(
                run.config.gpus, run.need_mb, run.config.workers, gpus, reserved, cpu_busy, run.config.split_model
            )
            if placed is None:
                position += 1
                run.queue_position, run.queue_reason = position, reason
                continue
            reserve(run, placed)
            cpu_busy = cpu_busy or run.config.gpus == []
            run.start(placed)


def _scheduler_loop() -> None:
    while True:
        _wake.wait(SCHEDULE_EVERY)
        _wake.clear()
        try:
            _schedule()
        except Exception as e:   # keep the loop alive; the next tick retries
            console(f"[experiments] Scheduler error: {e}")


def _ensure_scheduler() -> None:
    global _scheduler
    with _lock:
        if _scheduler is None or not _scheduler.is_alive():
            _scheduler = threading.Thread(target=_scheduler_loop, name="experiments-scheduler", daemon=True)
            _scheduler.start()


class StoredRun:
    """A finished (or interrupted) run read back from its run.json."""

    def __init__(self, kind: Kind, data: dict, run_dir: Path):
        self.kind = kind
        self.id = data["id"]
        self.status = data["status"]
        self.data = data
        self.run_dir = run_dir
        if data.get("variants"):
            self.variants = [Variant.from_dict(v) for v in data["variants"]]
        else:   # saved before experiments had variants: a Data Collector run on one model
            model = data["config"]["model"]
            self.variants = [Variant(key=model_dir_name(model), label=model, model=model)]

    def summary(self) -> dict:
        # Runs saved before variants existed get the same fields as newer ones
        return {
            "models": list(dict.fromkeys(v.model for v in self.variants)),
            "variants": [v.as_dict() for v in self.variants],
            **self.data,
        }

    def logs_after(self, after: int) -> dict:
        try:
            lines = (self.run_dir / "run.log").read_text().splitlines()
        except OSError:
            lines = []
        return {"lines": lines[after:], "next": len(lines)}

    def cancel(self) -> None:
        pass

    def rename(self, name: str | None) -> None:
        self.data["name"] = name
        (self.run_dir / RUN_FILE).write_text(json.dumps(self.data, indent=2))


def _load_stored(kind: Kind, run_dir: Path) -> StoredRun | None:
    try:
        return StoredRun(kind, json.loads((run_dir / RUN_FILE).read_text()), run_dir)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def get(kind: Kind, run_id: str) -> Experiment | StoredRun | None:
    if not RUN_ID_PATTERN.match(run_id):
        return None
    if run_id in _runs:
        run = _runs[run_id]
        return run if run.kind is kind else None
    return next((s for d in _all_runs_dirs(kind) if (s := _load_stored(kind, d / run_id))), None)


def all_runs(kind: Kind | None = None) -> list[Experiment | StoredRun]:
    """Every run of an experiment, or of all of them, newest first."""
    runs: dict[str, Experiment | StoredRun] = {}
    for k in [kind] if kind else KINDS.values():
        for runs_dir in _all_runs_dirs(k):
            if runs_dir.exists():
                for path in runs_dir.iterdir():
                    if RUN_ID_PATTERN.match(path.name) and path.name not in runs and (stored := _load_stored(k, path)):
                        runs[stored.id] = stored
    runs.update({i: r for i, r in _runs.items() if kind is None or r.kind is kind})
    return sorted(runs.values(), key=lambda r: r.id, reverse=True)


def active_runs(kind: Kind | None = None) -> list[Experiment]:
    """Running and queued runs, oldest first."""
    return sorted(
        (r for r in _runs.values() if r.status in ACTIVE_STATUSES and (kind is None or r.kind is kind)),
        key=lambda r: r.id,
    )


def _read_counter(path: Path) -> int:
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return 1


def _next_number() -> int:
    """The next run number, shared by every experiment: past the counter and every number in use."""
    with _lock:
        counter = max(_read_counter(COUNTER_FILE), _read_counter(LEGACY_COUNTER_FILE))
        used = [r.summary().get("number") or 0 for r in all_runs()]
        number = max(counter, max(used, default=0) + 1)
        COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
        COUNTER_FILE.write_text(str(number + 1))
        LEGACY_COUNTER_FILE.unlink(missing_ok=True)   # merged into COUNTER_FILE
        return number


def number_unnumbered_runs() -> None:
    """Give runs saved before run numbers existed a number, oldest first."""
    for run in sorted(all_runs(), key=lambda r: r.id):
        if isinstance(run, StoredRun) and not run.data.get("number"):
            run.data["number"] = _next_number()
            (run.run_dir / RUN_FILE).write_text(json.dumps(run.data, indent=2))


def mark_interrupted_runs() -> None:
    """Runs still marked active on disk died with a previous API process."""
    paths = [p for k in KINDS.values() for d in _all_runs_dirs(k) if d.exists() for p in d.glob(f"*/{RUN_FILE}")]
    for path in paths:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if data.get("status") in ACTIVE_STATUSES and data.get("id") not in _runs:
            data.update(status="interrupted", step=None, current=None, queue=None,
                        error="The API server stopped before this run finished.",
                        finished_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"))
            for worker in data.get("workers") or []:
                worker.update(current=None, step=None)
            path.write_text(json.dumps(data, indent=2))


def delete(kind: Kind, run_id: str) -> bool:
    """Delete a finished run and everything it saved (PCAPs, logs, results). False if unknown."""
    run = get(kind, run_id)
    if run is None:
        return False
    if run.status in ACTIVE_STATUSES:
        raise RunConflict(f"Run {run_id} is {run.status}. Cancel it before deleting it.")
    run_dir = run.run_dir.resolve()
    if run_dir.name != run_id or run_dir.parent not in {d.resolve() for d in _all_runs_dirs(kind)}:
        return False
    with _lock:
        _runs.pop(run_id, None)
    shutil.rmtree(run_dir, ignore_errors=True)
    return True


def shutdown(timeout: float = 60) -> None:
    """Cancel every active run and wait for their cleanup (called when the API stops)."""
    runs = active_runs()
    for run in runs:
        run.cancel()
    deadline = time.monotonic() + timeout
    for run in runs:
        run.join(max(0, deadline - time.monotonic()))


def remove_orphaned_resources() -> None:
    """
    Remove resources left by runs that died without cleaning up (server crash,
    kill -9, dev reload). Only touches resources carrying an experiment's run
    label, and images the app recorded as pulled.
    """
    if active_runs():
        return
    removed = []
    for kind in KINDS.values():
        label = f"label={kind.run_label}"
        containers = docker.run("ps", "-aq", "--filter", label, timeout=30)
        if containers.returncode != 0:
            console(f"[experiments] Skipping orphan cleanup: {containers.stderr.strip()}")
            return
        for cid in containers.stdout.split():
            if docker.run("rm", "-f", cid).returncode == 0:
                removed.append(f"container {cid}")
        for net in docker.run("network", "ls", "-q", "--filter", label).stdout.split():
            if docker.run("network", "rm", net).returncode == 0:
                removed.append(f"network {net}")
        images = docker.run("images", "--filter", label, "--format", "{{.Repository}}:{{.Tag}}")
        for image in images.stdout.split():
            if docker.run("image", "rm", image).returncode == 0:
                removed.append(f"image {image}")
    for image in _pulled_images():
        if docker.exists("image", image) and docker.run("image", "rm", image).returncode == 0:
            removed.append(f"image {image}")
    _set_pulled_images([])
    if removed:
        console(f"[experiments] Removed orphaned resources: {', '.join(removed)}")
