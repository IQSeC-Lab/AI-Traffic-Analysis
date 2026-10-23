"""
The capture of Agent to PLC (agent_plc.py). It is marble_engine.py's capture with a PLC added,
as infra_engine.py adds a database: each worker still keeps its Ollama and TLS proxy for its
share of the run, and for each task (and repetition), once per topology:
  1. Start OPC PLC in a fresh container on the worker's network, with the brewery of the
     task's state loaded from its nodes file (plc_plant.py), and the brewery's physics in a
     container sharing its network: the physics reaches the PLC on localhost, so none of its
     traffic is on the interface that is captured
  2. Once the physics has found every node it moves, start the tcpdump sidecar on the PLC's
     network interface
  3. Run MARBLE in a fresh container, started through toolbox/marble_plc.py: the agents reach
     the PLC by its container name, every tool call its own encrypted OPC UA connection
  4. Save the PCAP and which agent made each call and when (<stem>.tool_calls.json), beside
     the agents' LLM calls (<stem>.agent_calls.json), then remove the physics and the PLC

The capture holds the agents' traffic with the PLC only. Their calls to the model go to
another container and are not in it; Agent to LLM captures those.
"""

from __future__ import annotations

import time

from . import agent_plc as plc
from . import docker_cli as docker
from . import plc_plant as plant
from .engine import TOOLBOX_DIR, FatalRunError
from .marble_engine import MarbleExperiment

PLC_IMAGE = "mcr.microsoft.com/iotedge/opc-plc:2.15.12"
LAUNCHER = TOOLBOX_DIR / "marble_plc.py"
PHYSICS = TOOLBOX_DIR / "plc_physics.py"
START_TIMEOUT = 90   # seconds for the PLC to listen and the physics to find its nodes
# Boiler #2's overheat and maintenance events come every 120 and 300 s by default, inside a
# task. A day apart, none does.
BOILER_EVENTS_S = "86400"


class PlcExperiment(MarbleExperiment):
    LAUNCHER = LAUNCHER

    def _images(self) -> list[str]:
        return [*super()._images(), PLC_IMAGE]

    def _setup(self) -> None:
        super()._setup()
        if self._cancel.is_set():
            return
        self._set_step("Pulling the PLC image")
        docker.must("pull", PLC_IMAGE, ctx=f"docker pull {PLC_IMAGE}")
        # Each state's nodes file, kept with the run's configs. The PLC reads them as its own
        # user, not as the one the API runs as.
        self._nodes_dir.mkdir(parents=True, exist_ok=True)
        for state in plant.STATES:
            path = self._nodes_dir / f"{state}.json"
            path.write_text(plant.nodes_json(state))
            path.chmod(0o644)
        self._nodes_dir.chmod(0o755)
        self.log(f"[setup] ✓ The brewery's nodes files: {self._nodes_dir}")

    @property
    def _nodes_dir(self):
        return self.configs_dir / "plc"

    def _plc(self, k: int) -> str:
        return f"mallm-{self.id}-w{k + 1}-plc"

    def _physics(self, k: int) -> str:
        return f"mallm-{self.id}-w{k + 1}-physics"

    def _task_config(self, k: int, task: dict, topology: str) -> str:
        return plc.task_config(task, topology, self.config.model)

    def _capture_container(self, k: int, llm: str, stem: str) -> str:
        """A new PLC for the task, in the task's state, with its physics running."""
        name, physics = self._plc(k), self._physics(k)
        state = self.prompts[self._workers[k]["current"]["prompt"]]["state"]
        docker.rm_container(physics)
        docker.rm_container(name)
        self._set_step("Starting the PLC")
        docker.must(
            "run", "-d", "--name", name, "--label", self.label,
            "--hostname", name,
            "--network", self._workers[k]["network"],
            "-v", f"{self._nodes_dir}:/nodes:ro",
            PLC_IMAGE,
            f"--pn={plant.PORT}", f"--ph={name}",
            "--aa",   # trusts the agents' self-signed client certificates
            f"--nf=/nodes/{state}.json",
            f"--b2oi={BOILER_EVENTS_S}", f"--b2mi={BOILER_EVENTS_S}",
            ctx="start the PLC",
        )
        docker.must(
            "run", "-d", "--name", physics, "--label", self.label,
            "--network", f"container:{name}",
            "-v", f"{PHYSICS}:/plc_physics.py:ro",
            self.image, "python", "/plc_physics.py", "--state", state, "--port", str(plant.PORT),
            ctx="start the brewery's physics",
        )
        # The physics says READY once it is connected and has read every node it moves
        deadline = time.monotonic() + START_TIMEOUT
        while "READY" not in docker.run("logs", physics).stdout:
            if self._cancel.is_set():
                return name
            if time.monotonic() > deadline or not self._is_running(physics) or not self._is_running(name):
                own = docker.run("logs", "--tail", "15", physics)
                server = docker.run("logs", "--tail", "15", name)
                raise FatalRunError(
                    "The PLC did not start with its physics.\n"
                    f"Physics: {(own.stderr + own.stdout).strip()[-800:] or 'no output'}\n"
                    f"PLC: {(server.stderr + server.stdout).strip()[-800:] or 'no output'}"
                )
            time.sleep(0.5)
        self.log(f"[plc] ✓ Brewery ready ({state}): {name}:{plant.PORT}")
        return name

    def _agents_args(self, k: int, stem: str) -> list[str]:
        (self.results_dir / f"{stem}.tools.jsonl").unlink(missing_ok=True)
        return [
            "-e", f"MARBLE_PLC_HOST={self._plc(k)}",
            "-e", f"MARBLE_PLC_PORT={plant.PORT}",
            "-e", f"MARBLE_PLC_READ_ONLY={','.join(plant.READ_ONLY)}",
            "-e", f"MARBLE_TOOL_CALL_LOG=/out/{stem}.tools.jsonl",
        ]

    def _task_record(self, k: int, stem: str) -> dict:
        """The requests the agents sent, saved beside the PCAP like their LLM calls."""
        requests = self._tool_calls(stem)
        failed = [r for r in requests if r.get("status") == "error"]
        helped = sum(r.get("origin", "call") != "call" for r in requests)
        self.log(f"[plc] {len(requests)} request{'' if len(requests) == 1 else 's'} sent"
                 + (f", {len(failed)} refused" if failed else "") + (f", {helped} read from an answer that was not a call" if helped else ""))
        return {"requests": len(requests), "requests_failed": len(failed), "requests_helped": helped,
                "request_error": (failed[-1].get("error") or "")[:300] if failed else None}

    def _task_problem(self, record: dict) -> str | None:
        if not record.get("requests"):
            return "The agents sent no request to the PLC, so the capture holds nothing."
        if record["requests"] == record.get("requests_failed"):
            return f"The PLC refused every request the agents sent. The last one: {record.get('request_error')}"
        return None

    def _after_task(self, k: int) -> None:
        docker.rm_container(self._physics(k))
        docker.rm_container(self._plc(k))
