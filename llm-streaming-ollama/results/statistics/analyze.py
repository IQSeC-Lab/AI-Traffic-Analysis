#!/usr/bin/env python3
import os
import re
import glob
import json
import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter

from scapy.all import PcapReader, IP, IPv6, TCP, UDP, ICMP, ARP, DNS
from scapy.layers.http import HTTP

# ── Config ────────────────────────────────────────────────────────────────────
PCAP_DIR      = "../captures"
TARGET_MODEL  = "Qwen-Qwen3-14B-Base"
OUT_DIR       = "output"
os.makedirs(OUT_DIR, exist_ok=True)
parts = TARGET_MODEL.split("-")
name = [parts[0], parts[-1]]

# ── Filename parser ───────────────────────────────────────────────────────────
def parse_name(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r'(.*?)(?:[_-]?prompt[_-]?|[_-]?p?)(\d+)$', stem, re.IGNORECASE)
    if m:
        return m.group(1).rstrip("_- "), int(m.group(2))
    parts = stem.split("_")
    return ("_".join(parts[:-1]) if len(parts) > 1 else stem), None

# ── Packet classifier ─────────────────────────────────────────────────────────
def classify_packet(pkt):
    if pkt.haslayer(ARP):
        return "ARP"

    if pkt.haslayer(ICMP):
        return "ICMP"

    if pkt.haslayer(DNS):
        return "DNS"

    if pkt.haslayer(TCP):
        tcp = pkt[TCP]
        flags = tcp.flags

        http_ports = {80, 8080, 8000, 11434}
        is_http_port = (tcp.dport in http_ports or tcp.sport in http_ports)

        if is_http_port or pkt.haslayer(HTTP):
            payload = bytes(tcp.payload)
            if payload[:4] in (b"POST", b"GET ", b"HEAD", b"PUT "):
                return "HTTP Request"
            if payload[:4] in (b"HTTP",):
                return "HTTP Response"

        if flags & 0x02 and not (flags & 0x10):
            return "TCP SYN"

        if flags & 0x01 or flags & 0x04:
            return "TCP FIN/RST"

        if flags & 0x10 and len(bytes(tcp.payload)) == 0:
            return "TCP ACK"

        if len(bytes(tcp.payload)) > 0:
            return "TCP Data"

        return "TCP ACK"

    if pkt.haslayer(UDP):
        return "UDP"

    if pkt.haslayer(IPv6):
        return "IPv6 Other"

    return "Other"

# ── Collect PCAPs ─────────────────────────────────────────────────────────────
all_files = sorted(glob.glob(os.path.join(PCAP_DIR, "**", "*.pcap"), recursive=True))
model_files = [p for p in all_files if parse_name(p)[0] == TARGET_MODEL]

if not model_files:
    raise FileNotFoundError(
        f"No PCAPs found for model '{TARGET_MODEL}' under '{PCAP_DIR}'."
    )

print(f"Found {len(model_files)} PCAP(s) for {TARGET_MODEL}")

# ── Count packets ─────────────────────────────────────────────────────────────
counts = Counter()

for pcap_path in model_files:
    with PcapReader(pcap_path) as reader:
        for pkt in reader:
            counts[classify_packet(pkt)] += 1

total = sum(counts.values())

print(f"Total packets: {total}")
print(pd.Series(counts).sort_values(ascending=False).to_string())

# ── Prepare data (group <1%) ──────────────────────────────────────────────────
sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)

labels, values = [], []
other_sum = 0

for label, count in sorted_counts:
    pct = count / total * 100
    if pct < 1.0 and label != "Other":
        other_sum += count
    else:
        labels.append(label)
        values.append(count)

if other_sum > 0:
    labels.append("Other")
    values.append(other_sum)

# ── Plot (Matplotlib Donut Chart) ─────────────────────────────────────────────
plt.figure(figsize=(8, 8))

wedges, texts, autotexts = plt.pie(
    values,
    labels=labels,
    autopct='%1.1f%%',
    startangle=140,
    textprops={'fontsize': 10}
)

# Donut hole
centre_circle = plt.Circle((0, 0), 0.6, fc='white')
plt.gca().add_artist(centre_circle)

plt.title(
    f"Packet distribution — {TARGET_MODEL}\n"
    f"({len(model_files)} prompts aggregated)",
    fontsize=12
)

# ── Save image ────────────────────────────────────────────────────────────────
out_path = os.path.join(OUT_DIR, f"{name}_packet_distribution.png")

plt.savefig(out_path, dpi=300, bbox_inches='tight')
plt.close()

# ── Save metadata ─────────────────────────────────────────────────────────────
with open(out_path + ".meta.json", "w") as f:
    json.dump({
        "caption": f"Packet distribution for {TARGET_MODEL}",
        "description": "Donut chart of packet type distribution across all prompts."
    }, f)

print(f"Saved → {out_path}")