"""
Runs a MARBLE task whose agents work on a PLC over OPC UA (Agent to PLC). Mounted into the
agents' container with marble_launch.py and run in place of marble/main.py:

    python /marble_plc.py --config_path /configs/<task>.yaml
    python /marble_plc.py --check-model      # one tool call asked of the model, before a run

A task config asks for the environment with `environment: {type: PLC}`. The agents get four
tools: browse (what one folder or device holds), read (one value), write (one setting) and
call (a method). Each call opens its own OPC UA connection to the PLC (MARBLE_PLC_HOST),
encrypted with Basic256Sha256 and SignAndEncrypt, and closes it, so a call is one connection
in the capture, as a query is in Agent to Infrastructure. The first call of a task is two:
a client first asks the PLC for its endpoints and certificate over an unencrypted connection,
as OPC UA clients do, and the certificate is kept for the task's later calls.

What a call sends besides its own request: write reads the node first, to write the value
with the node's own type, and call finds the method's object and the types of its arguments.

The sensors the brewery's physics writes (toolbox/plc_physics.py) are writable on the server,
so write refuses them here (MARBLE_PLC_READ_ONLY) without contacting the PLC.
"""

import asyncio
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from asyncua import Client, ua
from asyncua.crypto.cert_gen import setup_self_signed_certificate
from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256
from cryptography.x509.oid import ExtendedKeyUsageOID

from marble_launch import ToolEnvironment, main

ENV_TYPE = "PLC"
NS = 3                 # the brewery's namespace: a bare id like FermenterA.Temperature is read as ns=3;s=FermenterA.Temperature
MAX_CHILDREN = 40      # of a browse shown to the agent
MAX_CHARS = 1500       # of one value shown to the agent
URI = "urn:mallm:agents"
ROOTS = {"", "objects", "root", "/", "i=85"}

_ID = {"type": "string", "description": "A node id, for example ns=3;s=FermenterA.Temperature"}
TOOLS = {
    "browse": {"type": "function", "function": {
        "name": "browse",
        "description": "List what one folder or device of the PLC holds: its folders, its values (with what each is and whether it can be changed) and its methods. Without a node_id, lists the top of the PLC.",
        "parameters": {"type": "object", "properties": {"node_id": _ID}, "required": [], "additionalProperties": False},
    }},
    "read": {"type": "function", "function": {
        "name": "read",
        "description": "Read the current value of one node of the PLC. Example: {\"node_id\": \"ns=3;s=FermenterA.Temperature\"}",
        "parameters": {"type": "object", "properties": {"node_id": _ID}, "required": ["node_id"], "additionalProperties": False},
    }},
    "write": {"type": "function", "function": {
        "name": "write",
        "description": "Change one setting of the PLC. Example: {\"node_id\": \"ns=3;s=FermenterB.CoolingOn\", \"value\": true}",
        "parameters": {"type": "object", "properties": {
            "node_id": _ID,
            "value": {"type": ["string", "number", "boolean"], "description": "The new value: a number, true or false, or text"},
        }, "required": ["node_id", "value"], "additionalProperties": False},
    }},
    "call": {"type": "function", "function": {
        "name": "call",
        "description": "Run a method of the PLC. Example: {\"method_id\": \"ns=4;i=7019\", \"arguments\": [false]}",
        "parameters": {"type": "object", "properties": {
            "method_id": {"type": "string", "description": "The node id of the method"},
            "arguments": {"type": "array", "items": {"type": ["string", "number", "boolean"]}, "description": "The method's arguments, in order"},
        }, "required": ["method_id"], "additionalProperties": False},
    }},
}

TRUE, FALSE = {"true", "on", "yes", "1", "open"}, {"false", "off", "no", "0", "closed", "close"}
INTEGERS = {ua.VariantType.SByte, ua.VariantType.Byte, ua.VariantType.Int16, ua.VariantType.UInt16,
            ua.VariantType.Int32, ua.VariantType.UInt32, ua.VariantType.Int64, ua.VariantType.UInt64}


def parse_id(text: Any) -> ua.NodeId:
    """A node id as the agent wrote it. ValueError when it isn't one."""
    text = str(text).strip().strip("\"'`")
    if text.lower() in ROOTS:
        return ua.NodeId(ua.ObjectIds.ObjectsFolder)
    try:
        return ua.NodeId.from_string(text if "=" in text else f"ns={NS};s={text}")
    except ua.UaStringParsingError:
        raise ValueError(f"{text!r} is not a node id. Node ids look like ns=3;s=FermenterA.Temperature or ns=4;i=6211")


def convert(value: Any, kind: ua.VariantType) -> Any:
    """`value` as the agent gave it, as a value of `kind`. ValueError when it can't be one."""
    if kind == ua.VariantType.Boolean:
        if isinstance(value, bool):
            return value
        word = str(value).strip().lower()
        if word in TRUE | FALSE:
            return word in TRUE
        raise ValueError(f"{value!r} is not true or false")
    if kind in (ua.VariantType.Double, ua.VariantType.Float) or kind in INTEGERS:
        if isinstance(value, bool):
            raise ValueError(f"{value!r} is not a number")
        number = re.search(r"-?\d+(?:\.\d+)?", str(value))
        if not number:
            raise ValueError(f"{value!r} is not a number")
        return float(number.group()) if kind in (ua.VariantType.Double, ua.VariantType.Float) else int(round(float(number.group())))
    if kind == ua.VariantType.String:
        return str(value)
    if kind == ua.VariantType.LocalizedText:
        return ua.LocalizedText(str(value))
    raise ValueError(f"a value of type {kind.name} can't be written with this tool")


def show(value: Any) -> str:
    """A value as the agent is shown it: numbers rounded, text cut short."""
    if isinstance(value, float):
        text = f"{round(value, 3):g}"
    elif isinstance(value, (list, tuple)):
        text = "[" + ", ".join(show(v) for v in value) + "]"
    elif isinstance(value, ua.LocalizedText):
        text = str(value.Text)
    elif isinstance(value, bytes):
        text = f"<{len(value)} bytes>"
    else:
        text = str(value)
    return text if len(text) <= MAX_CHARS else f"{text[:MAX_CHARS]}... ({len(text)} characters in all)"


def _reason(e: Exception) -> str:
    return " ".join(str(e).split())[:300] or type(e).__name__


class PlcEnvironment(ToolEnvironment):
    SHAPE = ('{"name": "read", "arguments": {"node_id": "<node id>"}}  or  '
             '{"name": "write", "arguments": {"node_id": "<node id>", "value": <new value>}}  or  '
             '{"name": "browse", "arguments": {"node_id": "<node id of a folder>"}}  or  '
             '{"name": "call", "arguments": {"method_id": "<node id of a method>", "arguments": [<values>]}}')
    CHECK_PROMPT = ("You are agent2, the operator of a brewery whose PLC speaks OPC UA. The temperature of "
                    "fermenter A is the node ns=3;s=FermenterA.Temperature. Read it. "
                    "You can solve the task by calling the read function.")

    def __init__(self, config: Dict[str, Any], name: str = "PLC Environment"):
        super().__init__(name, config)
        self._keys: Optional[tuple] = None              # this client's certificate and key files, made on the first call
        self._server_certificate: Optional[bytes] = None
        for tool, description in TOOLS.items():
            self.register_action(tool, handler=getattr(self, tool), description=description)

    def label(self, action: str, arguments: Dict[str, Any]) -> str:
        if action == "write":
            return f"write {arguments.get('node_id', '')} = {arguments.get('value', '')}"
        if action == "call":
            return f"call {arguments.get('method_id', '')}({', '.join(map(str, arguments.get('arguments') or []))})"
        return f"{action} {arguments.get('node_id') or ('Objects' if action == 'browse' else '')}"

    # ── One connection per call ──────────────────────────────────────────────

    async def _connect(self) -> Client:
        if self._keys is None:
            folder = Path(tempfile.mkdtemp(prefix="plc-client-"))
            key, cert = folder / "key.pem", folder / "cert.der"
            await setup_self_signed_certificate(key, cert, URI, "mallm-agents", [ExtendedKeyUsageOID.CLIENT_AUTH],
                                                {"commonName": "mallm-agents"})
            self._keys = (str(cert), str(key))
        host, port = os.environ.get("MARBLE_PLC_HOST"), os.environ.get("MARBLE_PLC_PORT", "50000")
        if not host:   # only in a check of the model, which never runs a tool
            raise ValueError("The PLC is not configured (MARBLE_PLC_HOST)")
        # No health probe while connected: a call's connection carries its own requests only
        client = Client(f"opc.tcp://{host}:{port}", timeout=15, watchdog_intervall=3600)
        client.application_uri = URI
        self._sent.append(time.time())   # the call starts when its first packet goes out, not when its key was made
        await client.set_security(SecurityPolicyBasic256Sha256, *self._keys, server_certificate=self._server_certificate,
                                  mode=ua.MessageSecurityMode.SignAndEncrypt)
        self._server_certificate = client.security_policy.peer_certificate
        await client.connect()
        return client

    def _run(self, tool: str, work, where: Any) -> Dict[str, Any]:
        """Run `work(client, node)` on a connection of its own, `where` being the node id the agent gave;
        its answer is (rows, text)."""
        async def go():
            node = parse_id(where)
            client = await self._connect()
            try:
                return await work(client, node)
            finally:
                await client.disconnect()
        try:
            # On a thread of its own: asyncio.run leaves the thread it runs on without an event loop,
            # and MARBLE's thread goes on to call the model through litellm
            with ThreadPoolExecutor(1) as pool:
                rows, text = pool.submit(asyncio.run, go()).result()
        except ValueError as e:
            return {"status": "error", "function_name": tool, "rows": None, "explanation": f"{_reason(e)}."}
        except ua.UaStatusCodeError as e:
            return {"status": "error", "function_name": tool, "rows": None,
                    "explanation": f"The PLC refused it: {_reason(e)} Check the node id against the ones in the task, or browse to find it."}
        except Exception as e:
            return {"status": "error", "function_name": tool, "rows": None,
                    "explanation": f"The PLC could not be reached: {type(e).__name__}: {_reason(e)}"}
        return {"status": "success", "function_name": tool, "rows": rows, "explanation": text}

    # ── The tools ────────────────────────────────────────────────────────────

    def browse(self, node_id: str = "") -> Dict[str, Any]:
        read_only = set(os.environ.get("MARBLE_PLC_READ_ONLY", "").split(","))

        async def work(client: Client, where: ua.NodeId):
            children = await client.get_node(where).get_children_descriptions()
            shown = children[:MAX_CHILDREN]
            variables = [c for c in shown if c.NodeClass == ua.NodeClass.Variable]
            # One read for every value's value, description and access level
            attributes = (ua.AttributeIds.Value, ua.AttributeIds.Description, ua.AttributeIds.AccessLevel)
            params = ua.ReadParameters()
            for c in variables:
                for attribute in attributes:
                    params.NodesToRead.append(ua.ReadValueId(NodeId=ua.NodeId(c.NodeId.Identifier, c.NodeId.NamespaceIndex), AttributeId=attribute))
            found = iter(await client.uaclient.read(params) if params.NodesToRead else [])
            lines = []
            for c in shown:
                nid = ua.NodeId(c.NodeId.Identifier, c.NodeId.NamespaceIndex).to_string()
                name = c.DisplayName.Text or c.BrowseName.Name
                if c.NodeClass == ua.NodeClass.Method:
                    lines.append(f"- {name} ({nid}): a method, run it with the call tool")
                elif c.NodeClass == ua.NodeClass.Variable:
                    value, description, access = next(found), next(found), next(found)
                    shown_value = show(value.Value.Value) if value.StatusCode.is_good() and value.Value else "(no value)"
                    about = description.Value.Value.Text if description.StatusCode.is_good() and description.Value and description.Value.Value else ""
                    writable = (access.StatusCode.is_good() and access.Value and access.Value.Value & ua.AccessLevel.CurrentWrite.mask
                                and nid not in read_only)
                    lines.append(f"- {name} ({nid}) = {shown_value}" + (f". {about}" if about and about != name else "")
                                 + f". {'Can be changed' if writable else 'Read only'}.")
                else:
                    lines.append(f"- {name} ({nid}): a folder or device, browse it to see what it holds")
            more = f"\n({len(children) - len(shown)} more not shown.)" if len(children) > len(shown) else ""
            if not lines:
                return 0, f"{where.to_string()} holds nothing to browse. Read it with the read tool."
            return len(children), f"{where.to_string()} holds:\n" + "\n".join(lines) + more

        return self._run("browse", work, node_id)

    def read(self, node_id: str) -> Dict[str, Any]:
        async def work(client: Client, where: ua.NodeId):
            value = await client.get_node(where).read_value()
            rows = len(value) if isinstance(value, (list, tuple)) else 1
            return rows, f"{where.to_string()} = {show(value)}"

        return self._run("read", work, node_id)

    def write(self, node_id: str, value: Any) -> Dict[str, Any]:
        try:
            guarded = parse_id(node_id).to_string() in os.environ.get("MARBLE_PLC_READ_ONLY", "").split(",")
        except ValueError:
            guarded = False   # _run says what is wrong with it
        if guarded:
            return {"status": "error", "function_name": "write", "rows": None,
                    "explanation": f"{parse_id(node_id).to_string()} is a sensor reading and can't be written. Change a setting instead."}

        async def work(client: Client, where: ua.NodeId):
            node = client.get_node(where)
            # One read of its value and its data type, which the new value is written as. The value's
            # own type can differ: OPC PLC keeps a whole number from its nodes file as Int64.
            current, declared = await node.read_attributes([ua.AttributeIds.Value, ua.AttributeIds.DataType])
            current.StatusCode.check()
            type_id = declared.Value.Value if declared.StatusCode.is_good() else None
            kind = (ua.VariantType(type_id.Identifier) if type_id is not None and type_id.NamespaceIndex == 0
                    and type_id.Identifier in ua.VariantType._value2member_map_ else current.Value.VariantType)
            if current.Value.is_array:
                raise ValueError(f"{where.to_string()} holds a list, which can't be written with this tool")
            new = convert(value, kind)
            await node.write_value(ua.DataValue(ua.Variant(new, kind)))
            return 1, f"Written: {where.to_string()} = {show(new)} (it was {show(current.Value.Value)})."

        return self._run("write", work, node_id)

    def call(self, method_id: str, arguments: Optional[List[Any]] = None) -> Dict[str, Any]:
        given = arguments if isinstance(arguments, list) else ([] if arguments in (None, "") else [arguments])

        async def work(client: Client, method: ua.NodeId):
            node = client.get_node(method)
            parent = await node.get_parent()
            try:
                wanted = await (await node.get_child("0:InputArguments")).read_value()
            except ua.UaStatusCodeError:   # a method without arguments
                wanted = []
            if len(given) != len(wanted):
                names = ", ".join(f"{a.Name} ({ua.VariantType(a.DataType.Identifier).name})" for a in wanted) or "none"
                raise ValueError(f"{method.to_string()} takes {len(wanted)} argument{'' if len(wanted) == 1 else 's'}: {names}")
            values = [ua.Variant(convert(v, ua.VariantType(a.DataType.Identifier)), ua.VariantType(a.DataType.Identifier))
                      for v, a in zip(given, wanted)]
            out = await parent.call_method(method, *values)
            return 1, f"Called {method.to_string()}" + (f"({', '.join(show(v.Value) for v in values)})" if values else "()") + (
                f". It returned {show(out)}." if out not in (None, []) else ". It ran.")

        return self._run("call", work, method_id)


if __name__ == "__main__":
    main(ENV_TYPE, PlcEnvironment)
