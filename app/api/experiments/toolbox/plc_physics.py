"""
The brewery's physics for Agent to PLC (plc_plant.py describes the plant). Nodes loaded from
OPC PLC's nodes file keep their value until a client writes it, so this is what makes the
plant move: once a second it reads the settings and writes the sensors they move.

    python /plc_physics.py --state normal|fault|changeover [--port 50000]

It runs in its own container sharing the PLC container's network (--network container:<plc>)
and reaches the PLC on localhost. That traffic stays on the loopback interface, so the task's
capture (tcpdump on eth0) never holds it. It connects encrypted, as the agents do, so the PLC
needs no unencrypted endpoint.

It prints READY once it has connected and read every node it uses, which is what the engine
waits for before the capture starts, and stops with ERROR when it can't.
"""

import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

from asyncua import Client, ua
from asyncua.crypto.cert_gen import setup_self_signed_certificate
from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256
from cryptography.x509.oid import ExtendedKeyUsageOID

NS = 3
FERMENTERS = ("FermenterA", "FermenterB", "FermenterC")
COOLING = 0.2          # °C a second while a fermenter's cooling is on
WARMING = 0.02         # °C a second while it is off: the heat of fermentation
COLDEST, WARMEST = 0.0, 30.0
DRAIN = 1.0            # % a second while a fermenter's outlet valve is open
LEAK = {"fault": ("FermenterC", 0.5)}   # % a second, whatever its valve says
REJECT_EVERY = {"fault": 5}             # every nth bottle is rejected; every 50th otherwise
CONNECT_TIMEOUT = 60   # seconds for the PLC to start listening

SETTINGS = [(f, n) for f in FERMENTERS for n in ("CoolingOn", "OutletValveOpen")] + [("BottlingLine", "Running"), ("BottlingLine", "Speed")]
SENSORS = [(f, n) for f in FERMENTERS for n in ("Temperature", "Level")] + [("BottlingLine", "BottlesFilled"), ("BottlingLine", "RejectCount")]
TYPES = {"Temperature": ua.VariantType.Double, "Level": ua.VariantType.Double,
         "BottlesFilled": ua.VariantType.Int32, "RejectCount": ua.VariantType.Int32}


def step(state: str, settings: dict, sensors: dict, line: dict) -> None:
    """One second of the plant: `sensors` is changed in place. `line` keeps the bottles not yet
    whole and how many were filled since the start, for the rejects."""
    for f in FERMENTERS:
        change = -COOLING if settings[(f, "CoolingOn")] else WARMING
        sensors[(f, "Temperature")] = round(min(WARMEST, max(COLDEST, sensors[(f, "Temperature")] + change)), 2)
        drop = DRAIN if settings[(f, "OutletValveOpen")] else 0.0
        if LEAK.get(state, (None,))[0] == f:
            drop += LEAK[state][1]
        sensors[(f, "Level")] = round(max(0.0, sensors[(f, "Level")] - drop), 2)
    if settings[("BottlingLine", "Running")] and settings[("BottlingLine", "Speed")] > 0:
        line["part"] += settings[("BottlingLine", "Speed")] / 60
        whole = int(line["part"])
        line["part"] -= whole
        every = REJECT_EVERY.get(state, 50)
        rejects = (line["made"] + whole) // every - line["made"] // every
        line["made"] += whole
        sensors[("BottlingLine", "BottlesFilled")] += whole
        sensors[("BottlingLine", "RejectCount")] += rejects


async def connect(port: int, folder: Path) -> Client:
    key, cert = folder / "physics.pem", folder / "physics.der"
    uri = "urn:mallm:plc-physics"
    await setup_self_signed_certificate(key, cert, uri, "localhost", [ExtendedKeyUsageOID.CLIENT_AUTH],
                                        {"commonName": "mallm-plc-physics"})
    deadline = time.monotonic() + CONNECT_TIMEOUT
    while True:
        client = Client(f"opc.tcp://localhost:{port}", timeout=10, watchdog_intervall=3600)
        client.application_uri = uri
        try:
            await client.set_security(SecurityPolicyBasic256Sha256, str(cert), str(key),
                                      mode=ua.MessageSecurityMode.SignAndEncrypt)
            await client.connect()
            return client
        except (OSError, asyncio.TimeoutError, ua.UaError) as e:
            if time.monotonic() > deadline:
                raise SystemExit(f"ERROR the PLC did not answer on port {port}: {type(e).__name__}: {e}")
            await asyncio.sleep(1)


async def run(state: str, port: int) -> None:
    with tempfile.TemporaryDirectory() as folder:
        client = await connect(port, Path(folder))
    node = lambda f, n: client.get_node(f"ns={NS};s={f}.{n}")
    setting_nodes = [node(f, n) for f, n in SETTINGS]
    sensor_nodes = [node(f, n) for f, n in SENSORS]
    try:
        sensors = dict(zip(SENSORS, await client.read_values(sensor_nodes)))
        await client.read_values(setting_nodes)
    except ua.UaError as e:
        raise SystemExit(f"ERROR a node of the brewery is not on the PLC: {e}")
    print("READY", flush=True)

    line = {"part": 0.0, "made": 0}
    tick = time.monotonic()
    while True:
        tick += 1.0
        await asyncio.sleep(max(0.0, tick - time.monotonic()))
        settings = dict(zip(SETTINGS, await client.read_values(setting_nodes)))
        step(state, settings, sensors, line)
        await client.write_values(sensor_nodes, [
            ua.DataValue(ua.Variant(sensors[(f, n)], TYPES[n])) for f, n in SENSORS
        ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, choices=["normal", "fault", "changeover"])
    parser.add_argument("--port", type=int, default=50000)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.state, args.port))
    except (ConnectionError, ua.UaError) as e:
        # The PLC goes away when the task ends; anything else before that is an error
        print(f"STOPPED {type(e).__name__}: {e}", file=sys.stderr, flush=True)
