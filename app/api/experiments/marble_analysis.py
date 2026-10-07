"""
Analytics for the agentic runs (marble_engine.py). They reuse the caching, grouping and
histograms of analysis.py; what differs is what a capture is.

A capture is one MARBLE task: several agents, each LLM call its own TLS connection to
the proxy in front of Ollama. So there is no single response stream, and the measurements
are those of marble-traffic-dataset's analysis (run_incremental_analysis.py), over the
encrypted application packets of every connection:
  - packets to or from the proxy's port that carry a payload, without retransmissions
    and without TLS handshake, change-cipher-spec and alert records
  - a burst is a run of consecutive packets in one direction; idle time is every gap
    between packets longer than a second

Which agent made each call comes from captures/<stem>.agent_calls.json, written by MARBLE
(not from the packets), and the task and its outcome from results/<stem>.json. A capture
without the latter is the task still running.
"""

from __future__ import annotations

import json
import math
import struct
from collections import Counter
from pathlib import Path
from statistics import median

from . import analysis
from .analysis import CACHE_VERSION, _PCAP_MAGIC, _gap_histogram, _median, _weighted_median
from .base import Variant

SERVICE_PORT = 11443       # the TLS proxy (marble_engine.PROXY_PORT)
IDLE_THRESHOLD = 1.0       # seconds
OUT, IN = 1, -1            # agents → model server, model server → agents

# The measurements of the dataset's traffic heatmap, under its names. All but the last are
# heavy-tailed, so the heatmap compares them on a log scale.
HEATMAP_METRICS = [
    ("total_packets", "Packets"),
    ("total_bytes", "Bytes"),
    ("task_duration", "Duration"),
    ("packets_per_second", "Packet rate"),
    ("total_bursts", "Bursts"),
    ("idle_time_fraction", "Idle fraction"),
]
LINEAR_METRICS = {"idle_time_fraction"}
SUMMARY_METRICS = [name for name, _ in HEATMAP_METRICS] + ["calls", "agents", "median_gap_ms"]


# =============================================================================
# PCAP reading
# =============================================================================


def _segment(frame: bytes, linktype: int) -> tuple[int, int, int, int, bytes] | None:
    """(src port, dst port, sequence number, flags, payload) of a TCP packet."""
    if linktype == 1:           # Ethernet
        offset, ethertype = 14, frame[12:14]
        if ethertype == b"\x81\x00":   # VLAN tag
            offset, ethertype = 18, frame[16:18]
    elif linktype == 113:       # Linux cooked capture
        offset, ethertype = 16, frame[14:16]
    elif linktype == 0:         # BSD loopback, as in the dataset's captures (collected on macOS)
        offset = 4
        ethertype = b"\x08\x00" if frame[offset:offset + 1] and frame[offset] >> 4 == 4 else b"\x86\xdd"
    else:
        return None

    ip = frame[offset:]
    if ethertype == b"\x08\x00" and len(ip) >= 20 and ip[9] == 6:        # IPv4 / TCP
        ip_header = (ip[0] & 0x0F) * 4
        end = int.from_bytes(ip[2:4], "big")
        tcp = ip[ip_header:end] if end > ip_header else ip[ip_header:]
    elif ethertype == b"\x86\xdd" and len(ip) >= 40 and ip[6] == 6:     # IPv6 / TCP
        tcp = ip[40:40 + int.from_bytes(ip[4:6], "big")]
    else:
        return None
    if len(tcp) < 20:
        return None
    return (
        int.from_bytes(tcp[0:2], "big"),
        int.from_bytes(tcp[2:4], "big"),
        int.from_bytes(tcp[4:8], "big"),
        tcp[13],
        tcp[(tcp[12] >> 4) * 4:],
    )


def _is_tls_control(payload: bytes) -> bool:
    """A handshake, change-cipher-spec or alert record: the connection's setup, not the call."""
    if len(payload) < 5:
        return False
    return payload[0] in (20, 21, 22) and payload[1] == 3 and payload[2] <= 4 and int.from_bytes(payload[3:5], "big") <= 18432


def read_packets(path: Path) -> tuple[list[tuple[float, int, int]], dict]:
    """The capture's application packets as (timestamp, direction, payload bytes), in time order,
    and what it holds in all: its packets, their bytes on the wire and its time span."""
    data = path.read_bytes()
    totals = {"packets": 0, "bytes": 0, "capture_s": 0.0}
    if len(data) < 24:
        return [], totals
    if data[:4] not in _PCAP_MAGIC:
        raise ValueError(f"{path.name} is not a libpcap file")
    endian, frac = _PCAP_MAGIC[data[:4]]
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    record = struct.Struct(endian + "IIII")

    kept: list[tuple[float, int, int]] = []
    seen: set[tuple[int, int, int, bytes]] = set()
    first = last = None
    pos = 24
    while pos + 16 <= len(data):
        sec, sub, incl, orig = record.unpack_from(data, pos)
        pos += 16
        frame = data[pos:pos + incl]
        pos += incl
        if len(frame) < incl:   # truncated last record (tcpdump stopped mid-write)
            break
        segment = _segment(frame, linktype)
        if segment is None:
            continue
        sport, dport, seq, flags, payload = segment
        t = sec + sub * frac
        first = t if first is None else first
        last = t
        totals["packets"] += 1
        totals["bytes"] += orig
        if dport == SERVICE_PORT:
            direction = OUT
        elif sport == SERVICE_PORT:
            direction = IN
        else:
            continue
        if not payload or flags & 0x07:     # FIN, SYN, RST and bare ACKs
            continue
        key = (sport, dport, seq, payload)
        if key in seen:                      # retransmission
            continue
        seen.add(key)
        if _is_tls_control(payload):
            continue
        kept.append((t, direction, len(payload)))
    if first is not None:
        totals["capture_s"] = last - first
    kept.sort(key=lambda p: p[0])
    return kept, totals


# =============================================================================
# Per-capture records
# =============================================================================


def traffic_metrics(packets: list[tuple[float, int, int]]) -> dict:
    """The six measurements of the heatmap, as the dataset's analysis defines them."""
    if not packets:
        return {name: None for name, _ in HEATMAP_METRICS}
    times = [p[0] for p in packets]
    duration = times[-1] - times[0] if len(times) > 1 else 0.0
    gaps = [b - a for a, b in zip(times, times[1:])]
    idle = sum(g for g in gaps if g > IDLE_THRESHOLD)
    return {
        "total_packets": len(packets),
        "total_bytes": sum(p[2] for p in packets),
        "task_duration": duration,
        "packets_per_second": len(packets) / duration if duration else 0.0,
        "total_bursts": 1 + sum(a[1] != b[1] for a, b in zip(packets, packets[1:])),
        "idle_time_fraction": idle / duration if duration else 0.0,
    }


def _calls(run_dir: Path, stem: str) -> list[dict]:
    """The task's LLM calls: [{"agent_id", "call_start", "call_end"}], in the order they started."""
    try:
        calls = json.loads((run_dir / "captures" / f"{stem}.agent_calls.json").read_text())
        return sorted((c for c in calls if isinstance(c, dict) and "call_start" in c), key=lambda c: c["call_start"])
    except (OSError, ValueError, TypeError):
        return []


def assign_agents(times: list[float], calls: list[dict]) -> list[str]:
    """The agent whose call was open when each packet was seen ("" when none was), as the
    dataset's analysis attributes them: the earliest call that covers the packet."""
    assigned = [""] * len(times)
    for call in calls:
        start, end, agent = float(call["call_start"]), float(call["call_end"]), str(call.get("agent_id"))
        for i, t in enumerate(times):
            if not assigned[i] and start <= t <= end:
                assigned[i] = agent
    return assigned


def build_record(pcap: Path, result_file: Path, index: int) -> dict:
    run_dir = pcap.parent.parent
    packets, totals = read_packets(pcap)
    incoming = [p for p in packets if p[1] == IN]
    sizes = [p[2] for p in incoming]
    gaps = [(b[0] - a[0]) * 1000 for a, b in zip(incoming, incoming[1:])]

    result = json.loads(result_file.read_text()) if result_file.exists() else None
    prompt, iteration, category = analysis._identity(run_dir, index, result or {})
    known = analysis._known_prompt(run_dir, prompt) or {}
    calls = _calls(run_dir, pcap.stem)
    return {
        "version": CACHE_VERSION,
        "index": index,
        "prompt": prompt,
        "iteration": iteration,
        "category": category,
        "task_id": (result or {}).get("task_id", known.get("task_id")),
        "worker": (result or {}).get("worker"),
        "gpus": (result or {}).get("gpus"),
        # "running" until MARBLE finishes with the task and its result is saved
        "status": "running" if result is None else "completed" if result.get("completed") else "failed",
        "error": (result or {}).get("error"),
        "metrics": {
            **totals,
            **traffic_metrics(packets),
            "incoming_packets": len(incoming),
            "median_packet_bytes": _median(sizes),
            "median_gap_ms": _median(gaps),
            "calls": len(calls) if result is not None else None,
            "agents": len({c.get("agent_id") for c in calls}) if result is not None else None,
            "run_s": (result or {}).get("duration_s"),
        },
        "size_counts": dict(Counter(sizes)),
        "gap_hist": _gap_histogram(gaps),
    }


# =============================================================================
# Run-level aggregates
# =============================================================================


def summarize(records: list[dict]) -> dict:
    """Medians over the tasks that completed; a task that didn't has only part of its traffic."""
    done = [r for r in records if r.get("status") == "completed"]

    def values(key: str) -> list[float]:
        return [r["metrics"][key] for r in done if r["metrics"].get(key) is not None]

    sizes = Counter()
    for r in done:
        sizes.update({int(k): v for k, v in r["size_counts"].items()})
    return {
        "captures": len(done),
        "failed": sum(r.get("status") == "failed" for r in records),
        **{f"median_{key}" if not key.startswith("median_") else key: _median(values(key)) for key in SUMMARY_METRICS},
        "median_packet_bytes": _weighted_median(sizes),
        "total_bytes": sum(r["metrics"].get("bytes") or 0 for r in records),
    }


def run_aggregate(run_id: str, run_dir: Path, variants: list[Variant]) -> dict:
    return analysis.run_aggregate(run_id, run_dir, variants, build=build_record, summarize=summarize)


def heatmap(aggregate: dict, variants: list[Variant]) -> list[dict]:
    """
    The dataset's traffic heatmap, for each topology of the run: per task category, the median
    of each measurement, standardized across the categories (so a row reads as "more or less
    than the other categories", in standard deviations).

    As there: a task counts once (the median of its repetitions), the heavy-tailed
    measurements are compared on a log scale, and only completed tasks count.
    """
    names = [name for name, _ in HEATMAP_METRICS]
    out = []
    for variant in variants:
        mine = [r for r in aggregate["records"] if r["variant"] == variant.key and r.get("status") == "completed"]
        by_task: dict[tuple[str, int], list[dict]] = {}
        for r in mine:
            by_task.setdefault((r["category"], r["prompt"]), []).append(r["metrics"])
        categories = list(dict.fromkeys(category for category, _ in by_task))
        raw, scaled = [], []
        for category in categories:
            tasks = [reps for (c, _), reps in by_task.items() if c == category]
            row_raw, row_scaled = [], []
            for name in names:
                per_task = [median(v) for reps in tasks if (v := [m[name] for m in reps if m.get(name) is not None])]
                row_raw.append(median(per_task) if per_task else None)
                transformed = per_task if name in LINEAR_METRICS else [math.log1p(max(v, 0)) for v in per_task]
                row_scaled.append(median(transformed) if transformed else None)
            raw.append(row_raw)
            scaled.append(row_scaled)
        z = [[None] * len(names) for _ in categories]
        for j in range(len(names)):
            column = [row[j] for row in scaled if row[j] is not None]
            if not column:
                continue
            mean = sum(column) / len(column)
            std = math.sqrt(sum((v - mean) ** 2 for v in column) / len(column)) or 1.0
            for i, row in enumerate(scaled):
                if row[j] is not None:
                    z[i][j] = (row[j] - mean) / std
        out.append({
            "key": variant.key,
            "label": variant.label,
            "categories": categories,
            "tasks": [sum(1 for c, _ in by_task if c == category) for category in categories],
            "z": z,
            "medians": raw,
        })
    return out


def find_capture(run_dir: Path, variants: list[Variant], stem: str) -> tuple[int, Variant] | None:
    return analysis.find_capture(run_dir, variants, stem)


def capture_detail(run_dir: Path, stem: str, index: int, variant: Variant, max_points: int = 4000) -> dict:
    record = analysis.capture_record(run_dir, stem, index, build=build_record)
    packets, _ = read_packets(run_dir / "captures" / f"{stem}.pcap")
    calls = _calls(run_dir, stem)
    t0 = min([p[0] for p in packets[:1]] + [float(c["call_start"]) for c in calls[:1]], default=0.0)

    assigned = assign_agents([p[0] for p in packets], calls)
    agents = []
    for agent in dict.fromkeys(str(c.get("agent_id")) for c in calls):
        own = [p for p, a in zip(packets, assigned) if a == agent]
        agents.append({
            "agent": agent,
            "calls": sum(str(c.get("agent_id")) == agent for c in calls),
            "packets": len(own),
            "bytes": sum(p[2] for p in own),
        })

    step = max(1, math.ceil(len(packets) / max_points))
    known = analysis._known_prompt(run_dir, record["prompt"]) or {}
    try:
        log = (run_dir / "logs" / f"{stem}.log").read_text(errors="replace")
    except OSError:
        log = ""
    return {
        "key": stem,
        "variant": variant.key,
        "index": index,
        "prompt": record["prompt"],
        "iteration": record["iteration"],
        "category": record["category"],
        "task_id": record.get("task_id"),
        "worker": record.get("worker"),
        "gpus": record.get("gpus"),
        "status": record.get("status"),
        "error": record.get("error"),
        "metrics": record["metrics"],
        "task_text": (known.get("text") or "").strip(),
        # [seconds since the task's first packet or call, payload bytes, 1 to the server / -1 from it]
        "timeline": [[round(p[0] - t0, 6), p[2], p[1]] for p in packets[::step]],
        "calls": [[str(c.get("agent_id")), round(float(c["call_start"]) - t0, 4), round(float(c["call_end"]) - t0, 4)]
                  for c in calls],
        "agents": agents,
        "unattributed_packets": sum(1 for a in assigned if not a),
        "log_tail": log[-6000:],
        "downsampled": step > 1,
    }

