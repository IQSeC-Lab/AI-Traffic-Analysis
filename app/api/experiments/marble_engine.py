"""
The capture of the agentic experiments, ported from toolbox/marble/scripts/capture_marble_dataset.py.
Runs use the same queue, workers, GPU scheduling and
Docker cleanup as every other experiment (engine.py); what differs is one capture.

Each worker keeps two containers for its whole share of the run, on its own isolated network:
  - Ollama with the run's model loaded, listening on its own loopback only
  - a TLS proxy sharing Ollama's network namespace: the one port open on the network
For each task (and repetition), once per topology:
  1. Start a tcpdump sidecar sharing that network namespace
  2. Run MARBLE in a fresh container: several agents work on the task, each LLM call a
     TLS connection to the proxy
  3. Save the PCAP, which agent made each call and when (<stem>.agent_calls.json), and the log

The original ran everything on one host, Ollama and the proxy on loopback, and cut each
task out of one continuous tcpdump by time. Here every task has its own capture, taken on
the model server's network interface, and the agents can't reach anything but the proxy.
Ollama stays up between tasks, as it did there, so no capture includes loading the model.
The model is one downloaded in Settings (settings/ollama_models.py).
"""

from __future__ import annotations

import json
import time
import traceback

from settings import ollama_models
from storage import MARBLE_DIR, OLLAMA_DIR

from . import docker_cli as docker
from . import engine
from . import topology_transfer as marble
from .base import Variant
from .engine import NETSHOOT_IMAGE, PCAP_FLUSH_SECONDS, TOOLBOX_DIR, Experiment, FatalRunError
from .ollama_engine import OLLAMA_IMAGE, ensure_ollama_image

DOCKERFILE   = TOOLBOX_DIR / "Dockerfile.marble"   # its build context is MARBLE_DIR
PROXY_SCRIPT = TOOLBOX_DIR / "tls_proxy.py"
IMAGE_REPO   = "mallm-marble"
OLLAMA_PORT  = 11434
PROXY_PORT   = 11443   # as in the original, so its analysis code reads these captures too
TASK_TIMEOUT = 300     # seconds, the original's limit for every category that runs here
LOAD_TIMEOUT = 900
IMPORT_TIMEOUT = 180
CHECK_TIMEOUT = 300
LOG_BYTES    = 400_000   # of a task's output kept in its log
MAX_FAILURES = 3         # tasks failing in a row on a worker before the run stops


# Run in the agents' image before a worker's first task: one call to the model the way MARBLE
# makes them (marble/llms/model_prompting.py), so a model server the agents can't use stops
# the run with the reason, instead of every task failing after its retries.
MODEL_CHECK = """
import os, ssl, urllib.error, urllib.request
base = os.environ["MARBLE_OLLAMA_PROXY_URL"]
try:
    status = urllib.request.urlopen(base + "/api/version", timeout=30, context=ssl._create_unverified_context()).status
except urllib.error.HTTPError as e:
    status = e.code
except Exception as e:
    raise SystemExit(f"MODEL_ERROR no answer from {base}: {type(e).__name__}: {e}")
if status != 200:
    raise SystemExit(f"MODEL_ERROR the model server answered HTTP {status} at {base}")
import litellm
litellm.ssl_verify = False
try:
    r = litellm.completion(model=os.environ["MODEL"], messages=[{"role": "user", "content": "Reply with OK."}],
                           max_tokens=8, temperature=0.0, base_url=base)
    print("MODEL_OK", repr(r.choices[0].message.content)[:80])
except Exception as e:
    raise SystemExit("MODEL_ERROR " + type(e).__name__ + ": " + " ".join(str(e).split())[:600])
"""


class MarbleExperiment(Experiment):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.image = f"{IMAGE_REPO}:{self.id}"
        self.configs_dir = self.run_dir / "configs"   # each task's MARBLE config, as it ran
        self._failures: dict[int, int] = {}

    def _title(self, prompt_no: int) -> str:
        task = self.prompts[prompt_no]
        return f"{task['category']} task {task['task_id']}"

    # ── Setup ────────────────────────────────────────────────────────────────

    def _setup(self) -> None:
        for folder in (self.captures_dir, self.logs_dir, self.results_dir, self.configs_dir):
            folder.mkdir(parents=True, exist_ok=True)
        if problem := marble.marble_problem():
            raise RuntimeError(problem)
        ollama_models.reserve_mb(self.config.model, on_gpu=False)   # still downloaded?

        with engine._lock:
            new = [img for img in (docker.base_image(DOCKERFILE), NETSHOOT_IMAGE) if not docker.exists("image", img)]
            engine._set_pulled_images(engine._pulled_images() + new)

        self._set_step("Building Docker image")
        self.log(f"[setup] Building {self.image} from {MARBLE_DIR}...")
        docker.must(
            "build", "-t", self.image, "--label", self.label,
            "-f", str(DOCKERFILE), str(MARBLE_DIR),
            ctx="docker build marble",
        )
        # A broken image would otherwise show as every task running out of time
        self._set_step("Checking the image")
        p = docker.run(
            "run", "--rm", "--name", f"mallm-{self.id}-check", "--label", self.label, "--network", "none",
            self.image, "python", "-c", "from marble.engine.engine import Engine",
            timeout=IMPORT_TIMEOUT,
        )
        if self._cancel.is_set():
            return
        if p.returncode != 0:
            tail = "\n".join((p.stderr or p.stdout).strip().splitlines()[-15:])
            raise RuntimeError(f"The image was built, but MARBLE doesn't start in it:\n{tail}")
        self._set_step("Pulling the Ollama and tcpdump images")
        docker.run("pull", NETSHOOT_IMAGE)
        ensure_ollama_image(self)
        self.log("[setup] ✓ Images ready.")

        self._set_step("Preparing network" + ("s" if len(self._workers) > 1 else ""))
        for w in self._workers:
            docker.must(
                "network", "create", "--driver", "bridge", "--internal",
                "--label", self.label, w["network"],
                ctx=f"create network {w['network']}",
            )
            self.log(f"[setup] ✓ Created isolated network: {w['network']}")

    # ── The worker's model server ────────────────────────────────────────────

    @staticmethod
    def _is_running(cname: str) -> bool:
        return docker.run("inspect", "-f", "{{.State.Running}}", cname).stdout.strip() == "true"

    def _model_server(self, k: int) -> str:
        """The worker's Ollama container, started with its TLS proxy when either isn't running."""
        llm = f"mallm-{self.id}-w{k + 1}-llm"
        tls = f"mallm-{self.id}-w{k + 1}-tls"
        if self._is_running(llm) and self._is_running(tls):
            return llm
        worker = self._workers[k]
        model = self.config.model
        docker.rm_container(tls)
        docker.rm_container(llm)

        self._set_step("Starting Ollama")
        docker.must(
            "run", "-d", "--name", llm, "--label", self.label,
            # Listening on loopback, Ollama answers 403 to a request addressed to a host name
            # other than localhost or its own. The agents address it by the container's name,
            # which the proxy passes on as it is, so that name is also its host name.
            "--hostname", llm,
            "--network", worker["network"],
            *engine._gpu_args(worker["gpus"]),
            "-v", f"{OLLAMA_DIR}:/root/.ollama",
            # Plaintext stays on the container's loopback; the proxy is the only way in
            "-e", f"OLLAMA_HOST=127.0.0.1:{OLLAMA_PORT}",
            "-e", "OLLAMA_KEEP_ALIVE=-1",
            OLLAMA_IMAGE,
            ctx="start Ollama",
        )
        deadline = time.monotonic() + 120
        while docker.run("exec", llm, "ollama", "list").returncode != 0:
            if self._cancel.is_set():
                return llm
            if time.monotonic() > deadline or not self._is_running(llm):
                logs = docker.run("logs", "--tail", "20", llm)
                raise FatalRunError(f"Ollama did not start: {(logs.stderr or logs.stdout).strip()[-500:]}")
            time.sleep(1)
        self.log(f"[ollama] ✓ Container started: {llm}")

        self._set_step("Loading the model")
        p = docker.run("exec", llm, "ollama", "run", model, "", timeout=LOAD_TIMEOUT)
        if self._cancel.is_set():
            return llm
        if p.returncode != 0:
            raise FatalRunError(f"Ollama could not load {model}: {(p.stderr or p.stdout).strip()[-500:]}")
        self.log(f"[ollama] ✓ Model loaded: {model}")

        docker.must(
            "run", "-d", "--name", tls, "--label", self.label,
            "--network", f"container:{llm}",
            "-v", f"{PROXY_SCRIPT}:/tls_proxy.py:ro",
            self.image, "python", "/tls_proxy.py",
            "--listen-port", str(PROXY_PORT),
            "--upstream-port", str(OLLAMA_PORT),
            "--cert", "/app/certs/cert.pem", "--key", "/app/certs/key.pem",
            ctx="start TLS proxy",
        )
        time.sleep(1)
        if not self._is_running(tls):
            logs = docker.run("logs", tls)
            raise FatalRunError(f"The TLS proxy stopped: {(logs.stderr or logs.stdout).strip()[-500:]}")
        self.log(f"[ollama] ✓ TLS proxy on {llm}:{PROXY_PORT}")

        self._set_step("Checking that the agents reach the model")
        p = docker.run(
            "run", "--rm", "--name", f"mallm-{self.id}-w{k + 1}-check", "--label", self.label,
            "--network", worker["network"],
            "-e", f"MARBLE_OLLAMA_PROXY_URL=https://{llm}:{PROXY_PORT}",
            "-e", f"MODEL=ollama/{model}",
            self.image, "python", "-c", MODEL_CHECK,
            timeout=CHECK_TIMEOUT,
        )
        if self._cancel.is_set():
            return llm
        if "MODEL_OK" not in p.stdout:
            found = [line for line in (p.stderr + p.stdout).splitlines() if line.startswith("MODEL_ERROR ")]
            error = found[-1][len("MODEL_ERROR "):] if found else (p.stderr or p.stdout).strip()[-400:] or "no output"
            logs = docker.run("logs", "--tail", "12", llm)
            raise FatalRunError(
                f"The agents can't get an answer from the model through the proxy: {error}\n"
                f"Ollama's log:\n{(logs.stderr or logs.stdout).strip()[-1500:]}"
            )
        self.log("[ollama] ✓ The agents reach the model")
        return llm

    # ── Per-task capture ─────────────────────────────────────────────────────

    def _run_prompt(self, k: int, variant: Variant, prompt: str, index: int) -> None:
        stem = f"{variant.key}-p{index:02d}"
        tc_cname = None
        record = None
        try:
            llm = self._model_server(k)
            if self._cancel.is_set():
                return
            self._set_step("Starting packet capture")
            tc_cname = self._start_capture(k, llm, stem)
            if self._cancel.is_set():
                return
            self._set_step("Running the agents")
            record = self._run_task(k, variant, llm, index, stem)
            self._set_step("Flushing capture")
            self._cancel.wait(PCAP_FLUSH_SECONDS)   # let tcpdump flush remaining packets
        except FatalRunError:
            raise
        except Exception as e:
            self.log(f"[experiment] ERROR on {stem}: {e}")
            self.log(traceback.format_exc())
        finally:
            self._set_step("Saving the PCAP")
            if tc_cname:
                self._stop_capture(tc_cname)
            pcap = self.captures_dir / f"{stem}.pcap"
            if pcap.exists():
                self.log(f"[capture] ✓ PCAP → {pcap} ({pcap.stat().st_size / 1024 / 1024:.2f} MB)")
            else:
                self.log(f"[capture] ⚠ PCAP not found for {stem}")

        if record is None or self._cancel.is_set():
            return
        # A task can fail on its own (the agents run out of time), but not every task: then
        # something every task needs is broken, and the rest of the run would only repeat it.
        self._failures[k] = 0 if record["completed"] else self._failures.get(k, 0) + 1
        if self._failures[k] >= MAX_FAILURES:
            raise FatalRunError(f"{MAX_FAILURES} tasks in a row failed. The last one: {record['error']}")

    def _run_task(self, k: int, variant: Variant, llm: str, index: int, stem: str) -> dict:
        """Run MARBLE on the task in a fresh container, and save what it did beside the PCAP."""
        worker = self._workers[k]
        current = worker["current"]
        task = self.prompts[current["prompt"]]
        topology = variant.key
        cname = f"mallm-{self.id}-w{k + 1}-agents"

        config = self.configs_dir / f"{stem}.yaml"
        source = marble.task_file(task["marble_category"], topology, task["task_id"])
        config.write_text(source.read_text().replace(marble.CONFIG_MODEL, f"ollama/{self.config.model}"))
        # MARBLE appends one line per LLM call here: which agent made it, when it started and ended
        calls_file = self.results_dir / f"{stem}.calls.jsonl"
        calls_file.unlink(missing_ok=True)
        docker.rm_container(cname)

        self.log(f"[agents] Running {self._title(current['prompt'])} ({task['agents']} agents, {variant.label})...")
        started = time.time()
        p = docker.run(
            "run", "--rm", "--name", cname, "--label", self.label,
            "--network", worker["network"],
            "-v", f"{self.configs_dir}:/configs:ro",
            "-v", f"{self.results_dir}:/out",
            "-e", f"MARBLE_OLLAMA_PROXY_URL=https://{llm}:{PROXY_PORT}",
            "-e", f"MARBLE_AGENT_CALL_LOG=/out/{calls_file.name}",
            self.image, "python", "main.py", "--config_path", f"/configs/{config.name}",
            timeout=TASK_TIMEOUT,
        )
        ended = time.time()
        timed_out = p.returncode == 124 and not p.stdout
        if timed_out:
            docker.rm_container(cname)
        output = p.stdout + p.stderr
        completed = marble.TOPOLOGIES[topology][2] in output
        error = None
        if timed_out:
            error = f"Stopped after {TASK_TIMEOUT} s without finishing."
        elif not completed:
            # MARBLE retries a failed model call and prints why each time; the traceback that
            # ends its output only says that the call returned nothing.
            attempts = [line.split(" failed: ", 1)[1] for line in output.splitlines()
                        if line.startswith("Attempt ") and " failed: " in line]
            error = (f"A call to the model failed: {attempts[0][:400].strip() or 'no reason given'}" if attempts else
                     " ".join(output.strip().splitlines()[-3:])[-400:] or "MARBLE stopped without finishing the task.")

        calls = []
        try:
            calls = [json.loads(line) for line in calls_file.read_text().splitlines() if line.strip()]
            calls_file.unlink()
        except (OSError, ValueError):
            pass
        # Beside the PCAP and in the dataset's format, so its analysis scripts read a run's captures as they are
        (self.captures_dir / f"{stem}.agent_calls.json").write_text(json.dumps(calls))
        record = {
            **current,
            "category": task["category"],
            "marble_category": task["marble_category"],
            "task_id": task["task_id"],
            "topology": topology,
            "model": variant.model,
            **variant.columns,
            "worker": k + 1,
            "gpus": worker["gpus"],
            "completed": completed,
            "error": error,
            "started": started,
            "duration_s": ended - started,
            "agents": len({c.get("agent_id") for c in calls}),
            "calls": len(calls),
        }
        (self.results_dir / f"{stem}.json").write_text(json.dumps(record))

        with (self.logs_dir / f"{stem}.log").open("w") as f:
            f.write("=" * 60 + "\n")
            f.write(f"{self._title(current['prompt']).upper()} · {variant.label.upper()}\n")
            f.write("=" * 60 + "\n")
            f.write(f"TASK:\n{task['text']}\n\n")
            f.write(f"RESULT: {'completed' if completed else error} ({ended - started:.1f} s, {len(calls)} LLM calls)\n")
            f.write("=" * 60 + "\n")
            f.write("MARBLE OUTPUT:\n")
            f.write("=" * 60 + "\n")
            f.write(output[-LOG_BYTES:])
        if completed:
            self.log(f"[agents] ✓ Completed in {ended - started:.1f} s, {len(calls)} LLM calls")
        else:
            self.log(f"[agents] ⚠ Not completed: {error}")
        return record
