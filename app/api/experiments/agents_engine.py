"""
The capture of Agent to Agents (agent_agents.py). Every agent of a task runs in a container of
its own, so what they say to each other crosses the worker's network, and that is what is
captured. Each worker keeps its Ollama and TLS proxy for its share of the run, as in
marble_engine.py; for each task (and repetition):
  1. Start one container per agent of the task (toolbox/marble_a2a.py --serve), named on the
     network by its agent id, and wait until each has built its MARBLE agent and listens
  2. Start one tcpdump sidecar per agent, on that agent's interface, keeping only the
     connections it answers on the A2A port. So every message is captured once, at the agent it
     was sent to, and neither the calls to the model nor the engine's requests are in it.
  3. Run MARBLE's engine in another container, its graph coordination unchanged: it asks each
     agent in turn to plan and act, and the agents start their conversations with each other
  4. Merge the sidecars' PCAPs into the task's one, in time order, save which agent sent each
     message and when (<stem>.tool_calls.json), and remove the agents

The engine runs the agents one at a time, as MARBLE does, so the messages of two conversations
never overlap and each packet is attributed to the agent that sent the message it belongs to.
"""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path

import yaml

from . import agent_agents as agents
from . import docker_cli as docker
from .analysis import _PCAP_MAGIC
from .engine import NETSHOOT_IMAGE, TOOLBOX_DIR, FatalRunError
from .marble_engine import PROXY_PORT, MarbleExperiment

LAUNCHER = TOOLBOX_DIR / "marble_a2a.py"
READY = "AGENT_READY"   # what an agent prints once it listens (marble_a2a.py)
START_TIMEOUT = 120     # seconds for every agent of a task to import MARBLE and listen


def merge_pcaps(parts: list[Path], out: Path) -> int:
    """Write the packets of tcpdump captures taken on several interfaces of one host (same link type)
    to `out`, in time order. Returns how many there are; nothing is written when no part has a header."""
    header, records = None, []
    for part in parts:
        data = part.read_bytes() if part.exists() else b""
        if len(data) < 24 or data[:4] not in _PCAP_MAGIC:
            continue
        endian, frac = _PCAP_MAGIC[data[:4]]
        header = header or data[:24]
        record = struct.Struct(endian + "IIII")
        pos = 24
        while pos + 16 <= len(data):
            sec, sub, incl, _ = record.unpack_from(data, pos)
            if pos + 16 + incl > len(data):   # truncated last record (tcpdump stopped mid-write)
                break
            records.append((sec + sub * frac, data[pos:pos + 16 + incl]))
            pos += 16 + incl
    if header is None:
        return 0
    records.sort(key=lambda r: r[0])
    tmp = out.with_name(f".{out.name}.part")
    tmp.write_bytes(header + b"".join(r for _, r in records))
    os.replace(tmp, out)   # the analysis may be reading the run's captures
    return len(records)


class AgentsExperiment(MarbleExperiment):
    LAUNCHER = LAUNCHER
    TASK_TIMEOUT = 900   # every turn of a conversation is a model call, made one at a time

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._agents: dict[int, list[str]] = {}    # worker: the agent ids of its task
        self._stems: dict[int, str] = {}
        self._sidecars: dict[str, tuple[str, list[str], list[Path]]] = {}   # first sidecar: (stem, sidecars, PCAPs)

    def _container(self, k: int, agent: str) -> str:
        return f"mallm-{self.id}-w{k + 1}-{agent}"

    def _task_config(self, k: int, task: dict, topology: str) -> str:
        return agents.task_config(super()._task_config(k, task, topology))

    def _agent_args(self, k: int, agent: str) -> list[str]:
        """More `docker run` options for one agent's container."""
        return []

    def _capture_container(self, k: int, llm: str, stem: str) -> str:
        """The task's agents, each in its own container, once all of them listen."""
        task = self.prompts[self._workers[k]["current"]["prompt"]]
        # The agents read their task when they start; _run_task writes the same file again
        config = self.configs_dir / f"{stem}.yaml"
        config.write_text(self._task_config(k, task, agents.TOPOLOGY))
        ids = [str(a["agent_id"]) for a in yaml.safe_load(config.read_text())["agents"]]
        self._agents[k], self._stems[k] = ids, stem
        (self.results_dir / f"{stem}.tools.jsonl").unlink(missing_ok=True)

        self._set_step("Starting the agents")
        for agent in ids:
            name = self._container(k, agent)
            docker.rm_container(name)
            docker.must(
                "run", "-d", "--name", name, "--label", self.label,
                "--network", self._workers[k]["network"], "--network-alias", agent,
                "-v", f"{self.configs_dir}:/configs:ro",
                "-v", f"{self.results_dir}:/out",
                "-e", f"MARBLE_OLLAMA_PROXY_URL=https://{llm}:{PROXY_PORT}",
                "-e", f"MARBLE_AGENT_CALL_LOG=/out/{stem}.calls.jsonl",
                "-e", f"MARBLE_TOOL_CALL_LOG=/out/{stem}.tools.jsonl",
                *self._agent_args(k, agent),
                *self._launcher_args(),
                self.image, "python", f"/{LAUNCHER.name}", "--serve", agent, "--config_path", f"/configs/{config.name}",
                ctx=f"start {agent}",
            )
        deadline = time.monotonic() + START_TIMEOUT
        waiting = list(ids)
        while waiting:
            if self._cancel.is_set():
                break
            for agent in list(waiting):
                logs = docker.run("logs", self._container(k, agent))
                if READY in logs.stdout:
                    waiting.remove(agent)
                elif time.monotonic() > deadline or not self._is_running(self._container(k, agent)):
                    raise FatalRunError(f"{agent} did not start: {(logs.stderr or logs.stdout).strip()[-800:]}")
            time.sleep(0.5)
        self.log(f"[agents] ✓ {len(ids)} agents listening, each in its own container: {', '.join(ids)}")
        return self._container(k, ids[0])

    def _start_capture(self, k: int, inf_container: str, stem: str) -> str:
        """A sidecar on every agent's interface, keeping the connections that agent answers."""
        port = agents.A2A_PORT
        sidecars, parts = [], []
        for agent in self._agents[k]:
            name = self._container(k, agent)
            ip = docker.run("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", name).stdout.strip()
            sidecar, part = f"{name}-tcpdump", self.results_dir / f"{stem}.{agent}.pcap"
            docker.rm_container(sidecar)
            part.unlink(missing_ok=True)
            p = docker.run(
                "run", "-d", "--name", sidecar, "--label", self.label,
                "--network", f"container:{name}",
                "-v", f"{self.results_dir}:/captures",
                "--cap-add=NET_RAW", "--cap-add=NET_ADMIN",
                NETSHOOT_IMAGE, "tcpdump", "-i", "eth0", "-s0", "-U", "-w", f"/captures/{part.name}",
                f"tcp and ((dst host {ip} and dst port {port}) or (src host {ip} and src port {port}))",
            )
            if not ip or p.returncode != 0:
                docker.run("rm", "-f", *sidecars, sidecar)
                raise FatalRunError(f"The packet capture of {agent} did not start: {(p.stderr or 'no address on the network').strip()[-400:]}")
            sidecars.append(sidecar)
            parts.append(part)
        time.sleep(2)
        unclear = []
        for sidecar in sidecars:
            logs = docker.run("logs", sidecar)
            if "listening on" not in (logs.stdout + logs.stderr).lower():
                unclear.append(sidecar)
        if unclear:
            self.log(f"[capture] ⚠ tcpdump status unclear on {', '.join(unclear)}")
        self.log(f"[capture] ✓ {len(sidecars)} sidecars active, one per agent → {stem}.pcap")
        self._sidecars[sidecars[0]] = (stem, sidecars, parts)
        return sidecars[0]

    def _stop_capture(self, tc_cname: str) -> None:
        stem, sidecars, parts = self._sidecars.pop(tc_cname, ("", [], []))
        if not sidecars:
            return
        docker.run("stop", *sidecars)
        docker.run("rm", "-f", *sidecars)
        packets = merge_pcaps(parts, self.captures_dir / f"{stem}.pcap")
        for part in parts:
            part.unlink(missing_ok=True)
        self.log(f"[capture] Merged {len(parts)} agents' captures: {packets} packets")

    def _task_record(self, k: int, stem: str) -> dict:
        """The messages the agents sent each other, saved beside the PCAP like their LLM calls."""
        messages = self._tool_calls(stem)
        failed = [m for m in messages if m.get("status") == "error"]
        helped = sum(m.get("origin", "call") != "call" for m in messages)
        self.log(f"[agents] {len(messages)} message{'' if len(messages) == 1 else 's'} between the agents"
                 + (f", {len(failed)} not answered" if failed else "")
                 + (f", {helped} started from an answer that was not a call" if helped else ""))
        return {"messages": len(messages), "messages_failed": len(failed), "messages_helped": helped,
                "message_error": (failed[-1].get("error") or "")[:300] if failed else None}

    def _task_problem(self, record: dict) -> str | None:
        if not record.get("messages"):
            return "The agents sent each other no message, so the capture holds nothing."
        if record["messages"] == record.get("messages_failed"):
            return f"No message between the agents was answered. The last one: {record.get('message_error')}"
        return None

    def _after_task(self, k: int) -> None:
        """Add each agent's own output to the task's log, then remove the agents."""
        stem = self._stems.pop(k, None)
        for agent in self._agents.pop(k, []):
            name = self._container(k, agent)
            if stem:
                logs = docker.run("logs", "--tail", "80", name)
                with (self.logs_dir / f"{stem}.log").open("a") as f:
                    f.write(f"\n{'=' * 60}\n{agent.upper()} (its own container):\n{'=' * 60}\n")
                    f.write((logs.stdout + logs.stderr)[-20_000:])
            docker.rm_container(name)
