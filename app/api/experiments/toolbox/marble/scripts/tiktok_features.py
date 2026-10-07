#!/usr/bin/env python3
"""Burst-level timing features from Rahman et al., "Tik-Tok: The Utility of
Packet Timing in Website Fingerprinting Attacks" (PETS 2020, arXiv:1902.06421),
adapted from website fingerprinting to agent-to-agent task fingerprinting.

Packets are read from a pcap with tcpdump (no scapy/tshark dependency, same
approach as pcap_features.py). Direction is derived from which side of the
connection is our lab's service ports (8081/8025/9022): packets flowing
toward those ports are "outgoing" (+1, agent -> service), packets flowing
from those ports are "incoming" (-1, service -> agent) -- the analogue of
client-to-server / server-to-client in the original WF setting.

Bursts are maximal runs of consecutive same-direction packets (Fig. 2 of the
paper). Eight raw per-instance timing features are extracted per burst or
per pair of consecutive bursts (Section 4.1.1):
  MED, Variance, Burst Length      (within a single burst)
  IMD, IBD-FF, IBD-LF              (any two consecutive bursts)
  IBD-IFF                          (two consecutive incoming bursts)
  IBD-OFF                          (two consecutive outgoing bursts)

Each raw feature list is then converted into a b-bin histogram against a
*global* distribution pooled across all instances (Section 4.1.2), producing
b features per type -> 8*b features per instance total.
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import subprocess
from pathlib import Path

LINE_RE = re.compile(
    r"^(?P<ts>\d+(?:\.\d+)?) IP "
    r"(?P<src>\d+(?:\.\d+){3})\.(?P<src_port>\d+) > "
    r"(?P<dst>\d+(?:\.\d+){3})\.(?P<dst_port>\d+): .* length (?P<length>\d+)"
)
SERVICE_PORTS = {"11443"}

FEATURE_TYPES = ["MED", "Variance", "BurstLength", "IMD", "IBD-FF", "IBD-LF", "IBD-IFF", "IBD-OFF"]


def read_packets(path: Path) -> list[tuple[float, int]]:
    """Return [(timestamp, direction)], direction +1 outgoing / -1 incoming."""
    result = subprocess.run(["tcpdump", "-nn", "-tt", "-r", str(path)], check=True, capture_output=True, text=True)
    packets = []
    for line in result.stdout.splitlines():
        m = LINE_RE.search(line)
        if not m:
            continue
        ts = float(m.group("ts"))
        if m.group("dst_port") in SERVICE_PORTS:
            direction = 1
        elif m.group("src_port") in SERVICE_PORTS:
            direction = -1
        else:
            continue
        packets.append((ts, direction))
    packets.sort(key=lambda p: p[0])
    return packets


def to_bursts(packets: list[tuple[float, int]]) -> list[tuple[int, list[float]]]:
    """Group consecutive same-direction packets into (direction, [timestamps]) bursts."""
    bursts: list[tuple[int, list[float]]] = []
    for ts, direction in packets:
        if bursts and bursts[-1][0] == direction:
            bursts[-1][1].append(ts)
        else:
            bursts.append((direction, [ts]))
    return bursts


def burst_features(bursts: list[tuple[int, list[float]]]) -> dict[str, list[float]]:
    """Raw (pre-histogram) feature values for one instance, per Section 4.1.1."""
    raw: dict[str, list[float]] = {k: [] for k in FEATURE_TYPES}
    if not bursts:
        return raw

    medians = []
    for direction, ts_list in bursts:
        med = statistics.median(ts_list)
        medians.append(med)
        raw["MED"].append(med)
        raw["Variance"].append(statistics.pvariance(ts_list) if len(ts_list) > 1 else 0.0)
        raw["BurstLength"].append(ts_list[-1] - ts_list[0])

    last_out_first, last_in_first = None, None
    for i in range(len(bursts)):
        direction, ts_list = bursts[i]
        if direction == 1:
            if last_out_first is not None:
                raw["IBD-OFF"].append(ts_list[0] - last_out_first)
            last_out_first = ts_list[0]
        else:
            if last_in_first is not None:
                raw["IBD-IFF"].append(ts_list[0] - last_in_first)
            last_in_first = ts_list[0]

    for i in range(1, len(bursts)):
        prev_ts, cur_ts = bursts[i - 1][1], bursts[i][1]
        raw["IMD"].append(medians[i] - medians[i - 1])
        raw["IBD-FF"].append(cur_ts[0] - prev_ts[0])
        raw["IBD-LF"].append(cur_ts[0] - prev_ts[-1])

    return raw


def build_global_bins(all_raw: list[dict[str, list[float]]], b: int) -> dict[str, list[float]]:
    """Equal-frequency bin edges per feature type, pooled across all instances."""
    edges: dict[str, list[float]] = {}
    for ftype in FEATURE_TYPES:
        pooled = sorted(v for raw in all_raw for v in raw[ftype])
        if not pooled:
            edges[ftype] = [0.0] * (b + 1)
            continue
        n = len(pooled)
        cuts = [pooled[min(int(round(i * n / b)), n - 1)] for i in range(b + 1)]
        cuts[0], cuts[-1] = pooled[0], pooled[-1]
        edges[ftype] = cuts
    return edges


def histogram_vector(raw: dict[str, list[float]], edges: dict[str, list[float]], b: int) -> list[float]:
    vec: list[float] = []
    for ftype in FEATURE_TYPES:
        values = raw[ftype]
        counts = [0] * b
        cuts = edges[ftype]
        for v in values:
            bin_idx = b - 1
            for i in range(b):
                lo, hi = cuts[i], cuts[i + 1]
                if lo <= v <= hi:
                    bin_idx = i
                    break
            counts[bin_idx] += 1
        total = sum(counts) or 1
        vec.extend(c / total for c in counts)
    return vec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pcaps", nargs="+", help="path.pcap:label")
    parser.add_argument("--bins", type=int, default=5, help="histogram bins per feature type (paper uses b=20 on a 1000x-larger dataset)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    entries = []
    for item in args.pcaps:
        path_text, label = item.rsplit(":", 1)
        entries.append((Path(path_text), label))

    all_raw = []
    for path, label in entries:
        bursts = to_bursts(read_packets(path))
        all_raw.append(burst_features(bursts))

    edges = build_global_bins(all_raw, args.bins)

    header = ["path", "label"] + [f"{ftype}_bin{i}" for ftype in FEATURE_TYPES for i in range(args.bins)]
    rows = []
    for (path, label), raw in zip(entries, all_raw):
        vec = histogram_vector(raw, edges, args.bins)
        rows.append([str(path), label] + vec)

    with open(args.out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"wrote {args.out}: {len(rows)} instances x {len(header)-2} features ({len(FEATURE_TYPES)} types x {args.bins} bins)")


if __name__ == "__main__":
    main()
