"""
The capture of Good Agent Bad Agent (good_bad_agents.py): Agent to Agents' (agents_engine.py),
with the team of the capture in place of the task's own agents, every agent's starting prompt
given to its own container, and every model of the run loaded in the worker's Ollama.
"""

from __future__ import annotations

from . import good_bad_agents as gb
from .agents_engine import AgentsExperiment
from .marble_engine import MarbleExperiment

AGENT_TIMEOUT = 300   # seconds of a task per agent: they act one at a time, and every turn is a model call


class GoodBadExperiment(AgentsExperiment):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TASK_TIMEOUT = AGENT_TIMEOUT * (self.config.good + self.config.bad)

    def _models(self) -> list[str]:
        return list(self.config.models)

    def _team(self, k: int) -> list[dict]:
        current = self._workers[k]["current"]
        variant = next(v for v in self.variants if v.key == current["variant"])
        return gb.team(self.config, variant, current["index"])

    def _task_config(self, k: int, task: dict, topology: str) -> str:
        current = self._workers[k]["current"]
        stem = f"{current['variant']}-p{current['index']:02d}"
        # The task's own file (MarbleExperiment's), before Agent to Agents adds its team text
        source = MarbleExperiment._task_config(self, k, task, topology)
        return gb.task_config(source, self.config, self._team(k), f"/out/{stem}.result.jsonl")

    def _agent_args(self, k: int, agent: str) -> list[str]:
        member = next(m for m in self._team(k) if m["agent_id"] == agent)
        return ["-e", f"MALLM_AGENT_BRIEF={self.config.bad_prompt if member['role'] == 'bad' else self.config.good_prompt}"]

    def _capture_container(self, k: int, llm: str, stem: str) -> str:
        (self.results_dir / f"{stem}.result.jsonl").unlink(missing_ok=True)   # MARBLE appends to it
        name = super()._capture_container(k, llm, stem)
        self.log("[team] " + ", ".join(f"{m['agent_id']} {m['role']} ({m['model']})" for m in self._team(k)))
        return name

    def _task_record(self, k: int, stem: str) -> dict:
        """Who was bad, and which model each agent called: nothing else records it."""
        return {**super()._task_record(k, stem), "team": self._team(k)}
