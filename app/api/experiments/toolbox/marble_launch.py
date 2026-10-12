"""
What the agentic experiments with tools of their own share when they start MARBLE
(marble_infra.py, marble_endpoint.py). Mounted into the agents' container beside them.

MARBLE's code is not changed: an environment is added to its engine when it starts, and a
task config asks for it with `environment: {type: ...}`.

Getting a small model to use its tools. MARBLE asks the model with tool_choice "auto", and
through Ollama that is a request for JSON: only an answer shaped
{"name": ..., "arguments": {...}} counts as a tool call. A 3B model often gets close without
getting there, and MARBLE then carries on with a task that never touched the database or
the web, so its capture holds nothing. Three things are done about it, in this order:
  1. An answer that is a call in all but shape is read as one: the arguments alone
     ({"sql": "SELECT ..."}), another spelling of the envelope ({"function": ...,
     "parameters": ...}), or what only one tool could be given (a SQL statement, an address).
  2. Otherwise the model is asked once more, shown its answer and the exact shape wanted.
  3. Before a worker's first task the same is tried once on its own (--check-model), so a
     model that can't do it stops the run with what it answered, instead of after three
     empty tasks.
A call made the first or second way is marked in the tool log ("origin"). What this can't
fix is a model that answers in prose twice; the run stops on that.

Every tool call is written to MARBLE_TOOL_CALL_LOG: which agent made it, when, what it
asked for and how it ended. That is the ground truth the capture is read against.
"""

import json
import os
import re
import runpy
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from marble.environments.base_env import BaseEnvironment

NUDGE = (
    "That was not a function call, so nothing was done. Answer again with only this JSON and nothing else, "
    "filled in for the next step of your task:\n{shape}"
)


class ToolEnvironment(BaseEnvironment):
    """An environment whose tools an experiment captures. A subclass registers its tools and says
    how to recognize a call the model wrote some other way (`recover_text`)."""

    # What the model is asked for when it didn't call a tool, and when it is checked before a run
    SHAPE = ""
    CHECK_PROMPT = ""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.origin = "call"   # how the call being applied was made: "call", "recovered" or "asked again"
        self._sent: List[float] = []   # when the requests of the call in progress went out

    def is_task_completed(self) -> bool:
        # MARBLE compares the last tool result with a ground truth as text; here there is neither
        return False

    def recover_text(self, text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """(tool, arguments) for an answer that is not JSON but can only be meant for one tool."""
        return None

    def label(self, action: str, arguments: Dict[str, Any]) -> str:
        """What a call asked for, as shown with it."""
        return str(action)

    def apply_action(self, agent_id: Optional[str], action_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        started = time.time()
        self._sent.clear()
        origin, self.origin = self.origin, "call"
        try:
            result = super().apply_action(agent_id, action_name, arguments)
        except (KeyError, TypeError) as e:
            # A tool that doesn't exist, or one called with other arguments than its own: the
            # agent is told, as with a call that fails, instead of the task ending
            result = {"status": "error", "function_name": action_name, "rows": None,
                      "explanation": f"The call could not be made ({type(e).__name__}: {e}). Use this shape: {self.SHAPE}"}
        # From when the request went out, not from the pause its host was owed before it
        self._log(agent_id, action_name, arguments, result, self._sent[0] if self._sent else started, time.time(), origin)
        return result

    def _log(self, agent_id, action, arguments, result, started: float, ended: float, origin: str) -> None:
        """One line per tool call. Never in the way of the task: a failure to write is only reported."""
        path = os.environ.get("MARBLE_TOOL_CALL_LOG")
        if not path:
            return
        try:
            result = result if isinstance(result, dict) else {}
            with open(path, "a") as f:
                f.write(json.dumps({
                    "agent_id": agent_id,
                    "call_start": started,
                    "call_end": ended,
                    "action": action,
                    "label": self.label(action, arguments if isinstance(arguments, dict) else {}),
                    "status": result.get("status", "error"),
                    "rows": result.get("rows"),
                    "error": result.get("explanation") if result.get("status") != "success" else None,
                    "origin": origin,
                }) + "\n")
        except Exception as e:
            print(f"WARNING: failed to log the tool call (non-fatal, continuing): {e}")


# =============================================================================
# Reading a tool call out of what the model answered
# =============================================================================


def _parameters(tools: List[dict]) -> Dict[str, List[str]]:
    """{tool: its required arguments} of the tools a call was offered."""
    return {
        t["function"]["name"]: list(t["function"].get("parameters", {}).get("required", []))
        for t in tools or [] if isinstance(t, dict) and "function" in t
    }


def _json_in(text: str) -> Any:
    """The JSON object an answer is, or holds between a code fence or other words."""
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except ValueError:
        pass
    first, last = text.find("{"), text.rfind("}")
    if 0 <= first < last:
        try:
            return json.loads(text[first:last + 1])
        except ValueError:
            pass
    return None


def recover(content: Optional[str], tools: Dict[str, List[str]], environment: Optional[ToolEnvironment]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """(tool, arguments) when the answer is a call to one of `tools` in all but shape, else None."""
    if not content or not content.strip():
        return None
    data = _json_in(content)
    if isinstance(data, dict):
        inner = data.get("function") if isinstance(data.get("function"), dict) else data
        name = inner.get("name") or inner.get("tool") or (data.get("function") if isinstance(data.get("function"), str) else None)
        arguments = next((inner[k] for k in ("arguments", "parameters", "args", "input") if k in inner), None)
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                arguments = None
        if name in tools and isinstance(arguments, dict):
            return name, arguments
        # The arguments alone: they have to fit one tool and no other
        fits = [tool for tool, required in tools.items() if required and all(isinstance(data.get(k), str) for k in required)]
        if len(fits) == 1:
            return fits[0], {k: data[k] for k in tools[fits[0]]}
    found = environment.recover_text(content) if environment else None
    return found if found and found[0] in tools else None


def _as_call(message, name: str, arguments: Dict[str, Any]):
    from litellm.types.utils import ChatCompletionMessageToolCall, Function
    message.tool_calls = [ChatCompletionMessageToolCall(
        id=f"call_{uuid.uuid4().hex[:24]}", type="function",
        function=Function(name=name, arguments=json.dumps(arguments)),
    )]
    return message


_environment: Optional[ToolEnvironment] = None


def tool_calling(model_prompting):
    """MARBLE's model call, with the two second chances for a tool call described at the top."""

    def prompting(*args, **kwargs):
        messages = model_prompting(*args, **kwargs)
        environment, offered = _environment, _parameters(kwargs.get("tools"))
        mine = {name: required for name, required in offered.items()
                if environment is not None and name in environment.action_handler_descriptions}
        if not mine or not messages or getattr(messages[0], "tool_calls", None):
            return messages
        found = recover(messages[0].content, mine, environment)
        origin = "recovered"
        if not found:
            asked = [*kwargs["messages"],
                     {"role": "assistant", "content": str(messages[0].content or "")},
                     {"role": "user", "content": NUDGE.format(shape=environment.SHAPE)}]
            again = model_prompting(*args, **{**kwargs, "messages": asked})
            if again and getattr(again[0], "tool_calls", None):
                environment.origin = "asked again"
                return again
            found = recover(again[0].content if again else None, mine, environment)
            origin = "asked again"
        if not found:
            return messages
        environment.origin = origin
        return [_as_call(messages[0], *found)]

    return prompting


# =============================================================================
# Starting MARBLE
# =============================================================================


def check_model(environment: ToolEnvironment) -> None:
    """Ask the model once for a tool call, the way an agent would, and say how it went."""
    global _environment
    from marble.llms.model_prompting import model_prompting

    _environment = environment
    tools = list(environment.action_handler_descriptions.values())
    try:
        message = tool_calling(model_prompting)(
            llm_model=os.environ["MODEL"], agent_id=None,
            messages=[{"role": "user", "content": environment.CHECK_PROMPT}],
            return_num=1, max_token_num=512, temperature=0.0, top_p=None, stream=None,
            tools=tools, tool_choice="auto",
        )[0]
    except Exception as e:
        raise SystemExit("TOOL_ERROR the model could not be asked: " + type(e).__name__ + ": " + " ".join(str(e).split())[:400])
    if getattr(message, "tool_calls", None):
        call = message.tool_calls[0].function
        how = {"call": "TOOL_OK", "recovered": "TOOL_RECOVERED", "asked again": "TOOL_ASKED_AGAIN"}[environment.origin]
        print(how, call.name, " ".join(str(call.arguments).split())[:200])
        return
    raise SystemExit("TOOL_ERROR " + " ".join(str(message.content or "(an empty answer)").split())[:500])


def main(env_type: str, environment_class) -> None:
    """Run MARBLE with `environment_class` added under the name `env_type`, or with --check-model
    only ask the model for one tool call."""
    import marble.agent.base_agent as base_agent
    from marble.engine.engine import Engine

    if "--check-model" in sys.argv:
        check_model(environment_class(config={"check": True}))
        return

    marble_environment = Engine._initialize_environment

    def initialize_environment(self, env_config: Dict[str, Any]) -> BaseEnvironment:
        global _environment
        if env_config.get("type") == env_type:
            _environment = environment_class(config=env_config)
            return _environment
        return marble_environment(self, env_config)

    Engine._initialize_environment = initialize_environment
    base_agent.model_prompting = tool_calling(base_agent.model_prompting)
    # MARBLE's own entry point, with the command line as it is (cwd is /app/marble)
    runpy.run_path("main.py", run_name="__main__")
