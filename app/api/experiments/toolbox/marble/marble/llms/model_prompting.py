import json
import os
import time

import litellm
from beartype import beartype
from beartype.typing import Any, Dict, List, Optional
from litellm.types.utils import Message

from marble.llms.error_handler import api_calling_error_exponential_backoff


def _log_agent_call(agent_id: Optional[str], call_start: float, call_end: float) -> None:
    # Sidecar log of (agent_id, call_start, call_end) for every LLM call, so
    # a task's single aggregated pcap can later be sub-sliced by which
    # agent(s) were actually talking during a given time window -- lets
    # analysis pick any subset of K agents post-hoc without needing to
    # re-capture. Off by default; capture_marble_dataset.py points
    # MARBLE_AGENT_CALL_LOG at a per-task file when it wants this.
    #
    # This must NEVER let a logging failure affect the real LLM call: this
    # function runs after litellm.completion() has already succeeded, and
    # model_prompting() is wrapped in a 5x-retry-with-backoff decorator that
    # catches *any* exception raised anywhere in the function body -- an
    # unguarded write here (e.g. the target directory not existing from a
    # subprocess's cwd, which happened in practice with a relative
    # --out-root) silently turned every real LLM call into 5 redundant
    # real LLM calls plus ~31s of backoff sleep before ultimately crashing
    # with a beartype violation on the resulting None return.
    try:
        _write_agent_call(agent_id, call_start, call_end)
    except Exception as e:
        print(f"WARNING: failed to log agent call (non-fatal, continuing): {e}")


def _write_agent_call(agent_id: Optional[str], call_start: float, call_end: float) -> None:
    if agent_id is None:
        return
    log_path = os.environ.get("MARBLE_AGENT_CALL_LOG")
    if not log_path:
        return
    with open(log_path, "a") as f:
        f.write(json.dumps({"agent_id": agent_id, "call_start": call_start, "call_end": call_end}) + "\n")


@beartype
@api_calling_error_exponential_backoff(retries=5, base_wait_time=1)
def model_prompting(
    llm_model: str,
    messages: List[Dict[str, str]],
    return_num: Optional[int] = 1,
    max_token_num: Optional[int] = 512,
    temperature: Optional[float] = 0.0,
    top_p: Optional[float] = None,
    stream: Optional[bool] = None,
    mode: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> List[Message]:
    """
    Select model via router in LiteLLM with support for function calling.
    """
    # litellm.set_verbose=True
    if "together_ai/TA" in llm_model:
        base_url = "https://api.ohmygpt.com/v1"
    elif llm_model.startswith("ollama/"):
        # Route through the local TLS-terminating proxy
        # (scripts/tls_ollama_proxy.py) so agent<->model traffic is
        # genuinely encrypted on the wire for capture, instead of hitting
        # Ollama's plaintext HTTP API directly. The proxy uses a self-signed
        # research-lab cert, so skip chain verification for it specifically.
        base_url = os.environ.get("MARBLE_OLLAMA_PROXY_URL", "http://127.0.0.1:11434")
        if base_url.startswith("https://"):
            litellm.ssl_verify = False
    else:
        base_url = None
    call_start = time.time()
    completion = litellm.completion(
        model=llm_model,
        messages=messages,
        max_tokens=max_token_num,
        n=return_num,
        top_p=top_p,
        temperature=temperature,
        stream=stream,
        tools=tools,
        tool_choice=tool_choice,
        base_url=base_url,
    )
    call_end = time.time()
    _log_agent_call(agent_id, call_start, call_end)
    message_0: Message = completion.choices[0].message
    assert message_0 is not None
    assert isinstance(message_0, Message)
    return [message_0]
