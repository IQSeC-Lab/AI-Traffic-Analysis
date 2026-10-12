"""
The capture of Agent to Endpoint (agent_endpoint.py). It is marble_engine.py's capture
moved to the agents' side of the network, on a network that reaches the internet:
  - The worker's network is a plain Docker bridge, not an isolated one. It is the only
    experiment where that is so.
  - Each worker keeps one more small container for its share of the run, which does nothing
    but own a network interface. The tcpdump sidecar listens on that interface, and every
    task's agents run inside it (docker run --network container:...), so the capture is
    what the agents send and receive: their requests to the sites, and their calls to the
    model, which go to the worker's own proxy on another port.
  - MARBLE is started through toolbox/marble_endpoint.py, which gives the agents their two
    tools, search and read. Beside the PCAP the run saves which agent made each request and
    when (<stem>.tool_calls.json).

Name lookups are not in the capture: Docker answers them inside the container.
"""

from __future__ import annotations

import os

from . import agent_endpoint as endpoint
from . import docker_cli as docker
from .engine import NETSHOOT_IMAGE, TOOLBOX_DIR, FatalRunError
from .marble_engine import MarbleExperiment

LAUNCHER = TOOLBOX_DIR / "marble_endpoint.py"
CHECK_TIMEOUT = 90
# Who the requests say they are from. Set MALLM_ENDPOINT_USER_AGENT on the API's host to add a way to reach you.
USER_AGENT = "RogueAgent-research/0.1 (encrypted traffic study)"
# Run in the agents' image before a worker's first task: the internet is something every task needs
REACH_CHECK = """
import os, requests
try:
    r = requests.get("https://medlineplus.gov/robots.txt", timeout=20, headers={"User-Agent": os.environ["MARBLE_ENDPOINT_USER_AGENT"]})
    print("REACH_OK", r.status_code)
except Exception as e:
    raise SystemExit("REACH_ERROR " + type(e).__name__ + ": " + " ".join(str(e).split())[:400])
"""


class EndpointExperiment(MarbleExperiment):
    LAUNCHER = LAUNCHER

    def _network_args(self) -> list[str]:
        return []

    def _uplink(self, k: int) -> str:
        return f"mallm-{self.id}-w{k + 1}-uplink"

    @property
    def _user_agent(self) -> str:
        return os.environ.get("MALLM_ENDPOINT_USER_AGENT") or USER_AGENT

    def _task_config(self, task: dict, topology: str) -> str:
        return endpoint.task_config(task, topology, self.config.model)

    def _capture_container(self, k: int, llm: str, stem: str) -> str:
        """The container whose interface the agents use, started and checked when it isn't running."""
        uplink = self._uplink(k)
        if self._is_running(uplink):
            return uplink
        docker.rm_container(uplink)
        self._set_step("Connecting the agents to the internet")
        docker.must(
            "run", "-d", "--name", uplink, "--label", self.label,
            "--network", self._workers[k]["network"],
            NETSHOOT_IMAGE, "sleep", "infinity",
            ctx="start the agents' network container",
        )
        p = docker.run(
            "run", "--rm", "--name", f"mallm-{self.id}-w{k + 1}-reach", "--label", self.label,
            "--network", f"container:{uplink}",
            "-e", f"MARBLE_ENDPOINT_USER_AGENT={self._user_agent}",
            self.image, "python", "-c", REACH_CHECK,
            timeout=CHECK_TIMEOUT,
        )
        if self._cancel.is_set():
            return uplink
        if "REACH_OK" not in p.stdout:
            found = [line for line in (p.stderr + p.stdout).splitlines() if line.startswith("REACH_ERROR ")]
            error = found[-1][len("REACH_ERROR "):] if found else (p.stderr or p.stdout).strip()[-400:] or "no output"
            raise FatalRunError(f"The agents' container can't reach the internet, which this experiment needs: {error}")
        self.log(f"[network] ✓ The agents reach the internet through {uplink}")
        return uplink

    def _agents_network(self, k: int) -> str:
        return f"container:{self._uplink(k)}"

    def _agents_args(self, k: int, stem: str) -> list[str]:
        (self.results_dir / f"{stem}.tools.jsonl").unlink(missing_ok=True)
        # A key for the National Vulnerability Database's API, when the API's host has one: ten times its pace
        key = os.environ.get("MALLM_NVD_API_KEY")
        return [
            "-e", f"MARBLE_TOOL_CALL_LOG=/out/{stem}.tools.jsonl",
            "-e", f"MARBLE_ENDPOINT_USER_AGENT={self._user_agent}",
            *(["-e", f"MARBLE_NVD_API_KEY={key}"] if key else []),
        ]

    def _task_record(self, k: int, stem: str) -> dict:
        requests = self._tool_calls(stem)
        failed = [r for r in requests if r.get("status") == "error"]
        helped = sum(r.get("origin", "call") != "call" for r in requests)
        self.log(f"[web] {len(requests)} tool call{'' if len(requests) == 1 else 's'} made"
                 + (f", {len(failed)} failed" if failed else "") + (f", {helped} read from an answer that was not a call" if helped else ""))
        return {"requests": len(requests), "requests_failed": len(failed), "requests_helped": helped,
                "request_error": (failed[-1].get("error") or "")[:300] if failed else None}

    def _task_problem(self, record: dict) -> str | None:
        if not record.get("requests"):
            return "The agents made no request to a site, so the capture holds nothing of them."
        if record["requests"] == record.get("requests_failed"):
            return f"Every request to the sites failed. The last one: {record.get('request_error')}"
        return None
