"""
The plant of Agent to PLC (agent_plc.py): a small brewery whose controller is a simulated PLC,
Microsoft's OPC PLC (OPC UA) in a container on the worker's own network. It is started again
for every task, so each task starts from the same values.

What the PLC holds:
  - the brewery, defined here and loaded with OPC PLC's nodes file (--nf): three fermenters,
    a bottling line, the active recipe and a stacklight. Sensors are read only for the agents;
    settings are what they can change.
  - Boiler #2, one of OPC PLC's own simulations: it heats to its target, switches its heater
    off, cools to its base temperature and switches it on again. Its heater also has a Switch
    method.
  - OPC PLC's own test nodes, which nothing in the tasks uses but which a browse shows.

Nodes from a nodes file keep their value until a client writes it, so the brewery's physics
runs beside the PLC (toolbox/plc_physics.py): once a second it reads the settings and writes
the sensors (a fermenter cools while its cooling is on, drains while its valve is open, the
line fills bottles while it runs). It talks to the PLC over the PLC container's own loopback,
which the capture (tcpdump on eth0) never sees. Writing the sensors is why they are writable
on the server; the agents' write tool refuses them instead (READ_ONLY).

A task starts from one of three states of the same plant, so every task's PLC has the same
nodes and a browse of it the same size: normal, fault (fermenter B too warm with its cooling
off, a leak in fermenter C, a bottling line rejecting bottles) and changeover (the line
stopped, fermenter C empty, a new recipe to load).
"""

from __future__ import annotations

import json
import math
import random

PORT = 50000
NS = 3   # the namespace OPC PLC puts the nodes file's nodes in (http://microsoft.com/Opc/OpcPlc/)
STATES = ("normal", "fault", "changeover")
TASKS_PER_CATEGORY = 2

FERMENTERS = ("FermenterA", "FermenterB", "FermenterC")
LOG_HOURS = 48     # of each fermenter's logs, one value an hour, oldest first

# Boiler #2 (OPC PLC's own): its variables and its heater's Switch method
BOILER = {
    "CurrentTemperature": "ns=4;i=6211",
    "TargetTemperature": "ns=4;i=6217",
    "HeaterState": "ns=4;i=6212",
    "Overheated": "ns=4;i=6214",
    "Switch": "ns=4;i=7019",
}


def node_id(folder: str, name: str) -> str:
    return f"ns={NS};s={folder}.{name}"


# (name, OPC UA type, sensor?, what it is). Sensors are written by the physics (or never change).
_FERMENTER = [
    ("Temperature", "Double", True, "Beer temperature in °C"),
    ("TargetTemperature", "Double", False, "Temperature the beer should be kept at, in °C"),
    ("CoolingOn", "Boolean", False, "Glycol cooling: while on the beer cools 0.2 °C a second, while off it warms 0.02 °C a second"),
    ("Level", "Double", True, "How full the fermenter is, in %"),
    ("OutletValveOpen", "Boolean", False, "Outlet valve to the bottling line: while open, the level drops 1 % a second"),
    ("Batch", "String", True, "Batch in the fermenter"),
    ("TemperatureLog", "Float", True, f"Temperature at each of the last {LOG_HOURS} hours, oldest first, in °C"),
    ("LevelLog", "Float", True, f"Level at each of the last {LOG_HOURS} hours, oldest first, in %"),
]
_LINE = [
    ("Running", "Boolean", False, "Whether the line is filling bottles"),
    ("Speed", "Int32", False, "Bottles filled a minute while running"),
    ("Mode", "String", False, "Auto or Manual"),
    ("BottlesFilled", "Int32", True, "Bottles filled since the counter was reset"),
    ("RejectCount", "Int32", True, "Bottles rejected since the counter was reset"),
    ("HourlyOutput", "Int32", True, "Bottles filled in each of the last 24 hours, oldest first"),
]
_RECIPE = [
    ("ActiveRecipe", "String", False, "Name of the recipe the brewhouse runs"),
    ("MashTemperature", "Double", False, "Mash temperature of the recipe, in °C"),
    ("BoilMinutes", "Int32", False, "Boil time of the recipe, in minutes"),
]
_STACKLIGHT = [
    ("Color", "String", False, "Light shown to the floor: green, yellow or red"),
]
FOLDERS: dict[str, list[tuple[str, str, bool, str]]] = {
    **{f: _FERMENTER for f in FERMENTERS},
    "BottlingLine": _LINE,
    "Recipe": _RECIPE,
    "Stacklight": _STACKLIGHT,
}

# The sensors the physics writes (toolbox/plc_physics.py), so they are writable on the server. The
# agents' write tool refuses these; the other sensors never change and are read only on the server too.
PHYSICS_WRITES = {"Temperature", "Level", "BottlesFilled", "RejectCount"}
READ_ONLY = [node_id(folder, name) for folder, nodes in FOLDERS.items() for name, _, sensor, _ in nodes
             if sensor and name in PHYSICS_WRITES]


def _logs(rng: random.Random) -> dict:
    """Each fermenter's 48 hours of history: a temperature with one warm spell (A peaks at hour 31)
    and a level that drains slowly, with one sudden drop in C (between hours 19 and 20)."""
    logs = {}
    for f, (base, level) in zip(FERMENTERS, ((18.0, 74.0), (12.0, 57.0), (19.0, 92.0))):
        temps = [base + 0.3 * math.sin(h / 5) + rng.uniform(-0.15, 0.15) for h in range(LOG_HOURS)]
        levels = [level - 0.04 * h + rng.uniform(-0.1, 0.1) for h in range(LOG_HOURS)]
        logs[f] = (temps, levels)
    temps_a = logs["FermenterA"][0]
    for h, extra in ((29, 0.6), (30, 1.1), (31, 1.6), (32, 0.9), (33, 0.4)):
        temps_a[h] += extra
    levels_c = logs["FermenterC"][1]
    for h in range(20, LOG_HOURS):
        levels_c[h] -= 27.0
    return {f: ([round(t, 2) for t in temps], [round(v, 1) for v in levels]) for f, (temps, levels) in logs.items()}


def _hourly(rng: random.Random) -> list[int]:
    """Bottles filled in each of the last 24 hours: busy by day, slow at night."""
    return [int(5400 * (0.55 + 0.45 * math.sin((h - 6) * math.pi / 12)) + rng.randint(-120, 120)) for h in range(24)]


def _values() -> dict[str, dict[str, dict]]:
    """{state: {folder: {name: value}}}: what each state starts from."""
    rng = random.Random(50000)
    logs, hourly = _logs(rng), _hourly(rng)
    fermenters = {
        "FermenterA": dict(Temperature=18.3, TargetTemperature=18.0, CoolingOn=False, Level=72.0, OutletValveOpen=False, Batch="IPA-0412"),
        "FermenterB": dict(Temperature=12.4, TargetTemperature=12.0, CoolingOn=False, Level=55.0, OutletValveOpen=False, Batch="LAGER-0409"),
        "FermenterC": dict(Temperature=20.4, TargetTemperature=19.0, CoolingOn=False, Level=88.0, OutletValveOpen=False, Batch="STOUT-0415"),
    }
    for f in FERMENTERS:
        fermenters[f]["TemperatureLog"], fermenters[f]["LevelLog"] = logs[f]
    normal = {
        **fermenters,
        "BottlingLine": dict(Running=True, Speed=90, Mode="Auto", BottlesFilled=4812, RejectCount=31, HourlyOutput=hourly),
        "Recipe": dict(ActiveRecipe="IPA", MashTemperature=65.0, BoilMinutes=60),
        "Stacklight": dict(Color="green"),
    }
    fault = json.loads(json.dumps(normal))
    fault["FermenterB"].update(Temperature=18.5)                  # cooling off: warming, 6.5 °C above target
    fault["BottlingLine"].update(RejectCount=412)                 # rejects every 5th bottle (physics)
    changeover = json.loads(json.dumps(normal))
    changeover["FermenterC"].update(Temperature=6.0, TargetTemperature=12.0, CoolingOn=True, Level=0.0,
                                    OutletValveOpen=True, Batch="(empty)")
    changeover["BottlingLine"].update(Running=False, Speed=0, Mode="Manual", BottlesFilled=0, RejectCount=0)
    changeover["Stacklight"].update(Color="yellow")
    return {"normal": normal, "fault": fault, "changeover": changeover}


VALUES = _values()


def nodes_json(state: str) -> str:
    """OPC PLC's nodes file for one state: the same nodes in every state, with its values."""
    values = VALUES[state]
    folders = []
    for folder, nodes in FOLDERS.items():
        node_list = []
        for name, kind, sensor, about in nodes:
            value = values[folder][name]
            node = {
                "NodeId": f"{folder}.{name}",
                "Name": name,
                "DataType": kind,
                "Value": value,
                "AccessLevel": "CurrentReadOrWrite" if not sensor or name in PHYSICS_WRITES else "CurrentRead",
                "Description": f"{'Sensor' if sensor else 'Setting'}: {about}",
            }
            if isinstance(value, list):
                node.update(ValueRank=1, ArrayDimensions=[len(value)])
            node_list.append(node)
        folders.append({"Folder": folder, "NodeList": node_list})
    # OPC PLC needs a node list in every folder, the outer one too
    return json.dumps({"Folder": "Brewery", "NodeList": [], "FolderList": folders}, indent=1, ensure_ascii=False)


# ── The tasks ────────────────────────────────────────────────────────────────

# What a request asks of the PLC: (label, what the form says about it)
CATEGORIES: dict[str, tuple[str, str]] = {
    "monitor": ("Monitor", "Read a few values and report them"),
    "compare": ("Compare", "Read the same values of several devices and pick one"),
    "explore": ("Explore", "Browse the PLC to find what it holds"),
    "control": ("Control", "Change settings or call a method"),
    "closed-loop": ("Closed loop", "Change a setting, watch the plant respond, change it back"),
    "incident": ("Incident", "Respond to a fault: act on it and raise the stacklight"),
    "history": ("History", "Read a 24 or 48-hour log and summarize it"),
    "anomaly": ("Anomaly", "Find something unusual, live or in a log"),
    "setpoints": ("Setpoints", "Write several settings at once"),
}

# (request, state the PLC starts in)
TASKS: dict[str, list[tuple[str, str]]] = {
    "monitor": [
        ("Report Boiler #2's current temperature, its target temperature and whether its heater is on.", "normal"),
        ("Report each fermenter's temperature and target temperature, and name any fermenter more than 1 °C off its target.", "normal"),
    ],
    "compare": [
        ("Which fermenter is furthest from its target temperature, and by how many degrees?", "normal"),
        ("Which fermenter holds the most beer, and which batch is in it?", "normal"),
    ],
    "explore": [
        ("Browse the brewery on the PLC and list every device in it with the values each one has.", "normal"),
        ("Find out which values of the bottling line an operator can change and which are sensor readings, and report both lists.", "normal"),
    ],
    "control": [
        ("Switch Boiler #2's heater off with its Switch method, then set the stacklight to red.", "normal"),
        ("Stop the bottling line and switch it to Manual mode.", "normal"),
    ],
    "closed-loop": [
        ("Fermenter B is too warm. Turn its cooling on, keep checking its temperature, and turn the cooling off once it is at its target.", "fault"),
        ("Start the bottling line at 120 bottles a minute, keep checking how many bottles are filled, and stop it once 100 bottles are filled.", "changeover"),
    ],
    "incident": [
        ("The bottling line is rejecting too many bottles. Stop it, set the stacklight to yellow, and report how many bottles were rejected.", "fault"),
        ("Fermenter C's level is dropping although its outlet valve is closed. Measure how fast it drops, set the stacklight to red, and report when the fermenter will be empty.", "fault"),
    ],
    "history": [
        ("Read fermenter A's temperature log and report at which hour it was warmest, and how warm.", "normal"),
        ("Read the bottling line's hourly output and report the busiest and the slowest hour.", "normal"),
    ],
    "anomaly": [
        ("Check every fermenter's temperature and level twice, a little apart, and report anything that is not as it should be.", "fault"),
        ("Fermenter C's level log has one sudden drop. Find at which hour it happened and how large it was.", "normal"),
    ],
    "setpoints": [
        ("Load the Stout recipe: set the active recipe to Stout, the mash temperature to 67 °C and the boil time to 75 minutes.", "changeover"),
        ("Fermenter C is empty and clean. Set its target temperature to 19 °C, close its outlet valve and switch its cooling off.", "changeover"),
    ],
}
assert set(TASKS) == set(CATEGORIES)
assert all(len(tasks) == TASKS_PER_CATEGORY and all(s in STATES for _, s in tasks) for tasks in TASKS.values())
assert PHYSICS_WRITES <= {name for nodes in FOLDERS.values() for name, _, sensor, _ in nodes if sensor}


def _node_table() -> str:
    """The plant as the agents are told it: every node with its id, and whether they may change it."""
    lines = []
    for folder, nodes in FOLDERS.items():
        lines.append(f"{folder} (folder ns={NS};s={folder}):")
        for name, kind, sensor, about in nodes:
            lines.append(f"  {node_id(folder, name)}  {kind}{' list' if name.endswith(('Log', 'Output')) else ''}, "
                         f"{'read only' if sensor else 'can be changed'}: {about}")
    lines.append("Boiler #2 (OPC PLC's own boiler):")
    lines.append(f"  {BOILER['CurrentTemperature']}  CurrentTemperature, Double, read only, in °C")
    lines.append(f"  {BOILER['TargetTemperature']}  TargetTemperature, Double, can be changed, in °C")
    lines.append(f"  {BOILER['HeaterState']}  HeaterState, Boolean, can be changed")
    lines.append(f"  {BOILER['Overheated']}  Overheated, Boolean, read only")
    lines.append(f"  {BOILER['Switch']}  Switch, a method with one argument: true turns the heater on, false off")
    return "\n".join(lines)


NODE_TABLE = _node_table()


def task_text(request: str, category: str) -> str:
    """What the agents are given: the plant, then the request. Explore requests are about finding
    the nodes, so they are only told where the brewery starts."""
    plant = (f"The brewery's nodes are in the folder ns={NS};s=Brewery." if category == "explore"
             else f"The PLC's nodes, by node id:\n{NODE_TABLE}")
    return (
        f"A brewery is run by a PLC that speaks OPC UA. {plant}\n\n"
        f"Request: {request}\n\n"
        "Carry out the request on the PLC with the browse, read, write and call tools, then check the result with a read."
    )


# The same three agents for every task; under the star topology MARBLE's planner hands them their work
AGENTS = [
    ("agent1", "agent1 is the brewery's control engineer. agent1 changes settings with the write tool and calls "
               "methods with the call tool, as the request needs. agent1 always answers with a tool call."),
    ("agent2", "agent2 is the brewery's operator. agent2 reads the values the request is about with the read tool, "
               "and browses the PLC with the browse tool to find a node. agent2 always answers with a tool call."),
    ("agent3", "agent3 is a reviewer. agent3 checks with the read tool that the request was carried out, and "
               "reports what the PLC holds now. agent3 always answers with a tool call."),
]
