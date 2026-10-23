"""
Runs the agents of an Agent to Agents task, each in a container of its own, so that what they
say to each other crosses the network. Mounted into the containers with marble_launch.py:

    python /marble_a2a.py --serve agent2 --config_path /configs/<task>.yaml   # one agent
    python /marble_a2a.py --config_path /configs/<task>.yaml                  # MARBLE's engine
    python /marble_a2a.py --check-model                                       # before a run

In MARBLE the agents of a task are objects in one process: when one starts a conversation with
another (new_communication_session), both sides of it are model calls made by the first, and
nothing is on the network. Here every agent is a process of its own:
  - `--serve` holds one MARBLE agent (a BaseAgent with its own profile and memory, built from
    the task config) and answers the other agents over A2A, the Agent2Agent protocol: JSON-RPC
    message/send over HTTPS on A2A_PORT, one TLS connection per message. That is what the
    capture holds.
  - Without it, MARBLE's engine runs its graph coordination unchanged, with each agent replaced
    by a stand-in that asks that agent's container to plan or act, on CONTROL_PORT. It is how the
    engine schedules the agents, as a method call is in MARBLE, and is left out of the capture.

A conversation keeps MARBLE's shape: the agent that starts it sends its message, the other
answers from its own memory with its own model call, and they take turns until one of them says
<end-of-session> or five turns have passed. Then the first sums it up, as in MARBLE, and the other
remembers what it was told and what it answered (in MARBLE it would not), so they work as a team.

Every message is written to MARBLE_TOOL_CALL_LOG by the agent that sent it: to whom, when it
went out and when the answer came back. That is the ground truth the capture is read against.
"""

import argparse
import json
import os
import runpy
import ssl
import sys
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, Dict, Optional

import requests
import urllib3

import marble.agent.base_agent as base_agent
import marble_launch
from marble.agent.base_agent import BaseAgent
from marble.llms.model_prompting import model_prompting
from marble_launch import ToolEnvironment, check_model, recover, tool_calling

A2A_PORT = 8443        # where every agent answers the others (agent_agents.A2A_PORT)
CONTROL_PORT = 9000    # where the engine asks an agent to plan or act; not captured
CERT, KEY = "/app/certs/cert.pem", "/app/certs/key.pem"   # the image's self-signed pair, as the model's proxy uses
READY = "AGENT_READY"  # printed once the agent listens (agents_engine.py waits for it)
END = "<end-of-session>"
COMMUNICATE = "new_communication_session"
MESSAGE_TIMEOUT = 300  # seconds for a peer to answer one message: one model call of its own
STARTUP_TIMEOUT = 120  # seconds the engine waits for an agent it has not reached yet
LABEL_CHARS = 400      # of a message, in the log (short lines: the agents append to one file)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class Messaging(ToolEnvironment):
    """Not an environment the agents act in: what marble_launch's second chances for a tool call
    need to know about new_communication_session, the one tool these agents have. MARBLE's agent
    offers and handles it itself."""

    SHAPE = ('{"name": "new_communication_session", "arguments": {"target_agent_id": "<the id of another agent>", '
             '"message": "<what you tell or ask it>"}}')
    CHECK_PROMPT = ("You are agent1, a software engineer. You work with agent2, a tester, on a bug in a function that adds "
                    "two numbers. Ask agent2 which inputs make it fail. You can send agent2 a message by calling the "
                    "new_communication_session function.")

    def __init__(self):
        super().__init__("Messaging", {})
        self.action_handler_descriptions[COMMUNICATE] = {"type": "function", "function": {
            "name": COMMUNICATE,
            "description": "Send a message to another agent and begin a conversation with it",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_agent_id": {"type": "string", "description": "The ID of the agent to talk to"},
                    "message": {"type": "string", "description": "The first message to send it"},
                },
                "required": ["target_agent_id", "message"],
                "additionalProperties": False,
            },
        }}


MESSAGING = Messaging()


# =============================================================================
# A2A: one message and its answer
# =============================================================================


def _text(message: Dict[str, Any]) -> str:
    return "".join(str(p.get("text", "")) for p in message.get("parts") or [] if p.get("kind") == "text")


def send(sender: str, target: str, session_id: str, text: str, origin: str) -> Optional[str]:
    """Send `text` to `target` with A2A's message/send, on a connection of its own (no session is
    kept), and log it. The answer, or None when there was none."""
    body = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send", "params": {"message": {
        "kind": "message", "role": "user", "messageId": uuid.uuid4().hex, "contextId": session_id,
        "parts": [{"kind": "text", "text": text}], "metadata": {"from": sender},
    }}}
    started = time.time()
    reply, error = None, None
    try:
        r = requests.post(f"https://{target}:{A2A_PORT}/", json=body, timeout=MESSAGE_TIMEOUT, verify=False)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise RuntimeError(data["error"].get("message") or "an error without a message")
        reply = _text(data["result"])
    except Exception as e:
        error = f"{type(e).__name__}: {' '.join(str(e).split())[:300]}"
    _log(sender, target, session_id, text, started, time.time(), error, origin)
    return reply


def _log(sender, target, session_id, text, started, ended, error, origin) -> None:
    """One line per message. Never in the way of the task: a failure to write is only reported."""
    path = os.environ.get("MARBLE_TOOL_CALL_LOG")
    if not path:
        return
    try:
        with open(path, "a") as f:
            f.write(json.dumps({
                "agent_id": sender,
                "peer": target,
                "session": session_id,
                "call_start": started,
                "call_end": ended,
                "action": "message/send",
                "label": f"To {target}: {' '.join(text.split())}"[:LABEL_CHARS],
                "status": "error" if error else "success",
                "error": error,
                "origin": origin,
            }) + "\n")
    except Exception as e:
        print(f"WARNING: failed to log the message (non-fatal, continuing): {e}")


# =============================================================================
# The agent
# =============================================================================


class NetworkAgent(BaseAgent):
    """A MARBLE agent whose conversations with the other agents go over the network: it sends its
    side of them, and answers theirs (`answer`)."""

    task = ""   # the task of the run, for a conversation another agent starts

    def reply_to(self, other_id: str, task: str) -> str:
        """This agent's turn in its conversation with `other_id`: MARBLE's prompt for a turn
        (BaseAgent._handle_new_communication_session), answered by this agent's own model call."""
        other = self.agent_graph.agents[other_id]
        communicate_to = {"type": "function", "function": {
            "name": "communicate_to",
            "description": f"Send a message to a specific target agent:- {other_id} (session_other_agent.profile)",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string", "description": "The initial message to send to the target agent"}},
                "required": ["target_agent_id", "message"],
                "additionalProperties": False,
            },
        }}
        prompt = (
            f"These are your memory: {self.memory}\n"
            f"The task is: {task}. \n"
            f"Please respond to {other_id}({other.profile}). \n"
            f"Your previous chat history: {self.seralize_message(session_id=self.session_id)}.\n"
            f"You should answer to this question {self.msg_box[self.session_id][other_id][-1][1]} using your memory, and other relevant context. \n"
            f"Return <end-of-session> if you cannot answer using information you have right now. \n"
            f"You are talking to {other_id}. You cannot talk with anyone else.\n"
            f"From {self.agent_id} to {other_id}:"
        )
        result = model_prompting(
            llm_model=self.llm, agent_id=self.agent_id,
            messages=[{"role": "system", "content": self.system_message}, {"role": "user", "content": prompt}],
            return_num=1, max_token_num=512, temperature=0.0, top_p=None, stream=None,
            tools=[communicate_to], tool_choice="required",
        )[0]
        if result.tool_calls:
            try:
                return str(json.loads(result.tool_calls[0].function.arguments)["message"])
            except (ValueError, KeyError, TypeError):
                pass
        # MARBLE sends nothing on such a turn. Here a call in all but shape ({"message": ...}) is read
        # as one, and any other answer is sent as it is
        found = recover(result.content, {"communicate_to": ["message"]}, None)
        return str(found[1]["message"]) if found else result.content or ""

    def answer(self, sender: str, session_id: str, message: str) -> str:
        """Another agent's message in its conversation with this one, and this agent's answer."""
        self.session_id = session_id
        self.msg_box[session_id][sender].append((self.RECV_FROM, message))
        reply = ""
        if END not in message:   # otherwise it ended the conversation: nothing to answer
            reply = self.reply_to(sender, self.task_history[-1] if self.task_history else self.task)
            self.msg_box[session_id][sender].append((self.FORWARD_TO, reply))
        # So that this agent works with what its teammate told it when it next plans and acts. In
        # MARBLE only the agent that started a conversation remembers it.
        self.memory.update(self.agent_id, {"type": "action_communicate", "action_name": "answered", "from": sender,
                                           "message": message, "answer": reply})
        return reply

    def _handle_new_communication_session(self, target_agent_id: str, message: str, session_id: str, task: str,
                                          turns: int = 5) -> Dict[str, Any]:
        """MARBLE's conversation between two agents, with the other agent's turns taken by the other agent."""
        origin, MESSAGING.origin = MESSAGING.origin, "call"   # how the model asked for it (marble_launch.tool_calling)
        if target_agent_id == self.agent_id or target_agent_id not in self.agent_graph.agents:
            return {"success": False, "error": f"Target agent {target_agent_id} not found in agent graph"}
        sid = str(session_id)
        self.session_id = sid
        box = self.msg_box[sid][target_agent_id]
        turn = 0
        while True:
            box.append((self.FORWARD_TO, message))
            reply = send(self.agent_id, target_agent_id, sid, message, origin)
            origin = "call"
            if reply is None:
                if turn == 0:
                    return {"success": False, "error": f"{target_agent_id} did not answer the message"}
                break
            if END in message:   # this agent ended it; the other was told and did not answer
                break
            box.append((self.RECV_FROM, reply))
            turn += 1
            if END in reply or turn >= turns:
                break
            message = self.reply_to(target_agent_id, task)
            turn += 1

        # As MARBLE ends a conversation: the agent that started it sums it up and remembers that
        system_message_summary = (
            "You are an advanced summarizer agent designed to condense and clarify the history of conversations between multiple agents. "
            "Your task is to analyze dialogues from various participants and generate a cohesive summary that captures the key points, themes, and decisions made throughout the interactions.\n\n"
            "Your primary objectives are:\n\n"
            "1. Contextual Analysis: Carefully review the entire conversation history to understand the context, including the roles of different agents and the progression of discussions.\n\n"
            "2. Identify Key Themes: Extract the main themes, topics, and significant moments in the dialogue, noting any recurring issues or points of contention.\n\n"
            "3. Summarize Conversations: Create a clear and concise summary that outlines the conversation's flow, important exchanges, decisions made, and any action items that emerged. Ensure that the summary reflects the contributions of each agent without losing the overall narrative.\n\n"
            "4. Highlight Outcomes: Emphasize any conclusions reached or actions agreed upon by the agents, providing a sense of closure to the summarized conversation.\n\n"
            "5. Engage with User Input: If the user has specific interests or focuses within the conversation, inquire to tailor the summary accordingly, ensuring it meets their needs.\n\n"
            "When composing the summary, maintain clarity, coherence, and logical organization. Your goal is to provide a comprehensive yet succinct overview that enables users to understand the essence of the multi-agent dialogue at a glance."
        )
        history = self.seralize_message(session_id=sid)
        summary = model_prompting(
            llm_model=self.llm, agent_id=self.agent_id,
            messages=[{"role": "system", "content": system_message_summary},
                      {"role": "user", "content": f"These are an chat history: {history}\n"
                                                  f"Please summarize information in the chat history relevant to the task: {task}."}],
            return_num=1, max_token_num=512, temperature=0.0, top_p=None, stream=None,
        )[0].content or ""
        self.memory.update(self.agent_id, {"type": "action_communicate", "action_name": "communicate_to", "result": summary})
        return {"success": True, "message": f"Successfully completed session {sid}", "full_chat_history": history,
                "session_id": summary}


def build_agent(agent_id: str, config_path: str) -> NetworkAgent:
    """The agent `agent_id` of the task, as MARBLE's engine builds it (Engine.__init__), with the
    other agents beside it only for their profiles and its relationships to them."""
    from marble.configs.config import Config
    from marble.environments import BaseEnvironment
    from marble.graph.agent_graph import AgentGraph

    config = Config.load(config_path)
    environment = BaseEnvironment(name="Base Environment", config=config.environment)
    # Good Agent Bad Agent: this agent's own starting prompt, given to its container only, so the
    # others (which read its profile from the task config) never see it. Before the agent is
    # built: its system message is made from its profile then.
    brief = os.environ.get("MALLM_AGENT_BRIEF", "").strip()
    configs = [{**a, "profile": f"{str(a.get('profile') or '').strip()} {brief}".strip()} if brief and a.get("agent_id") == agent_id else a
               for a in config.agents]
    agents = [(NetworkAgent if a.get("agent_id") == agent_id else BaseAgent)(config=a, env=environment, model=a.get("llm", config.llm))
              for a in configs]
    graph = AgentGraph(agents, config)
    for agent in agents:
        agent.set_agent_graph(graph)
    me = graph.agents.get(agent_id)
    if not isinstance(me, NetworkAgent):
        raise SystemExit(f"The task has no agent {agent_id}.")
    me.task = config.task.get("content", "")
    return me


# =============================================================================
# The agent's two ports
# =============================================================================


class _Handler(BaseHTTPRequestHandler):
    agent: NetworkAgent

    def _reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> Any:
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

    def log_message(self, *args) -> None:   # one line per request would bury the agent's own log
        pass


class A2AHandler(_Handler):
    """message/send from another agent: its message in, this agent's answer out."""

    def do_POST(self) -> None:
        request: Dict[str, Any] = {}
        try:
            request = self._body()
            if request.get("method") != "message/send":
                return self._reply(200, {"jsonrpc": "2.0", "id": request.get("id"),
                                         "error": {"code": -32601, "message": "Method not found"}})
            message = request["params"]["message"]
            sender, session = str(message["metadata"]["from"]), str(message["contextId"])
        except Exception as e:
            return self._reply(200, {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                                     "error": {"code": -32602, "message": f"Invalid params: {e}"}})
        try:
            text = self.agent.answer(sender, session, _text(message))
        except Exception as e:
            traceback.print_exc()
            return self._reply(200, {"jsonrpc": "2.0", "id": request.get("id"),
                                     "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}})
        self._reply(200, {"jsonrpc": "2.0", "id": request.get("id"), "result": {
            "kind": "message", "role": "agent", "messageId": uuid.uuid4().hex, "contextId": session,
            "parts": [{"kind": "text", "text": text}],
        }})


class ControlHandler(_Handler):
    """The engine's requests: /plan (BaseAgent.plan_task) and /act (BaseAgent.act)."""

    def do_POST(self) -> None:
        try:
            body = self._body()
            if self.path == "/plan":
                return self._reply(200, {"task": self.agent.plan_task()})
            if self.path == "/act":
                output, communication = self.agent.act(str(body["task"]))
                return self._reply(200, {"output": output, "communication": communication,
                                         "token_usage": self.agent.token_usage})
            self._reply(404, {"error": f"No {self.path} here"})
        except Exception as e:
            traceback.print_exc()
            self._reply(500, {"error": f"{type(e).__name__}: {e}"})


def serve(agent_id: str, config_path: str) -> None:
    agent = build_agent(agent_id, config_path)
    a2a = ThreadingHTTPServer(("0.0.0.0", A2A_PORT), type("Handler", (A2AHandler,), {"agent": agent}))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT, KEY)
    a2a.socket = context.wrap_socket(a2a.socket, server_side=True)
    control = ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), type("Handler", (ControlHandler,), {"agent": agent}))
    Thread(target=a2a.serve_forever, daemon=True).start()
    print(READY, agent_id, flush=True)
    control.serve_forever()


# =============================================================================
# MARBLE's engine, with the agents elsewhere
# =============================================================================


class RemoteAgent(BaseAgent):
    """What MARBLE's engine holds for an agent that runs in its own container (by its id on the
    network): it asks that agent to plan or act, and gives back what it answered."""

    _reached = False

    def _post(self, path: str, body: dict) -> dict:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while True:
            try:
                r = requests.post(f"http://{self.agent_id}:{CONTROL_PORT}{path}", json=body, timeout=None)
                break
            except requests.ConnectionError:
                # Only before the agent first answered: afterwards a request that broke may have been carried out
                if self._reached or time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        self._reached = True
        data = r.json()
        if r.status_code != 200:
            raise RuntimeError(f"{self.agent_id}: {data.get('error')}")
        return data

    def plan_task(self) -> Optional[str]:
        return self._post("/plan", {})["task"]

    def act(self, task: str) -> Any:
        self.task_history.append(task)
        data = self._post("/act", {"task": task})
        self.token_usage = int(data.get("token_usage") or 0)
        return data["output"], data["communication"]


def main() -> None:
    marble_launch._environment = MESSAGING
    base_agent.model_prompting = tool_calling(base_agent.model_prompting)   # BaseAgent.act's call, with second chances
    if "--check-model" in sys.argv:
        check_model(MESSAGING)
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", metavar="AGENT_ID")
    parser.add_argument("--config_path", required=True)
    args, _ = parser.parse_known_args()
    if args.serve:
        serve(args.serve, args.config_path)
        return
    import marble.engine.engine as engine

    engine.BaseAgent = RemoteAgent   # what Engine._initialize_agents builds
    sys.argv = [sys.argv[0], "--config_path", args.config_path]
    # MARBLE's own entry point (cwd is /app/marble)
    runpy.run_path("main.py", run_name="__main__")


if __name__ == "__main__":
    main()
