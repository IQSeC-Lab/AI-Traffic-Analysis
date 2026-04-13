#!/usr/bin/env python3
import os
import numpy as np
import matplotlib.pyplot as plt
from scapy.all import rdpcap, TCP

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
PCAP_DIR    = "test/"   # folder with *-p01.pcap files
OUT_PNG     = "itt_p01_400_multi_models.png"
MAX_POINTS  = 400            # length of token sequence
BIG_GAP_SEC = 0.3            # threshold to detect TTFT / big stall

# Map unique substrings in filenames -> label + color
MODEL_CONFIG = {
    "nvidia-AceReason-Nemotron-14B": {
        "label": "Nemotron 14B",
        "color": "#1f77b4",  # blue
    },
    "Qwen-Qwen3-14B-Base": {
        "label": "Qwen3 14B Base",
        "color": "#ff7f0e",  # orange
    },
    "rubenroy-Zurich-14B-GCV2-5m": {
        "label": "Zurich 14B GCV2-5m",
        "color": "#2ca02c",  # green
    },
    # add more models here as needed
}


# -------------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------------
def extract_times(pcap_path):
    """
    Return sorted array of packet arrival times (float seconds)
    for TCP packets in this pcap. Assume pcap is already filtered
    to the LLM response direction (server -> client).
    """
    packets = rdpcap(pcap_path)
    data_pkts = [p for p in packets if TCP in p]
    if len(data_pkts) < 3:
        return None

    times = np.array([float(p.time) for p in data_pkts])
    times.sort()
    return times


def strip_to_streaming(times, big_gap=BIG_GAP_SEC):
    """
    Given packet times, compute inter-arrival times dt and
    drop everything up to and including the first "big" gap,
    interpreted as TTFT / connection setup.
    Returns (times_stream, dt_stream).
    """
    if times is None or len(times) < 3:
        return None, None

    dt_full = np.diff(times)          # length N-1
    # find first gap larger than big_gap
    big_indices = np.where(dt_full > big_gap)[0]
    if len(big_indices) == 0:
        # no large gap, just use everything
        return times[1:], dt_full

    first_big = big_indices[0]
    # keep points strictly after that big gap
    times_stream = times[first_big + 1:]          # aligned with dt indices
    dt_stream = dt_full[first_big + 1:]
    return times_stream, dt_stream


def load_clean_dt(pcap_path, max_points=MAX_POINTS, big_gap=BIG_GAP_SEC):
    """
    Full pipeline for one pcap:
    - extract TCP packet arrival times
    - drop handshake / TTFT via first large gap
    - return first max_points inter-arrival times
    """
    times = extract_times(pcap_path)
    if times is None:
        return None

    times_stream, dt_stream = strip_to_streaming(times, big_gap=big_gap)
    if dt_stream is None or len(dt_stream) == 0:
        return None

    dt_stream = dt_stream[:max_points]
    return dt_stream


# -------------------------------------------------------------------
# MAIN PLOTTING
# -------------------------------------------------------------------
def main():
    plt.figure(figsize=(10, 5))

    for fname in os.listdir(PCAP_DIR):
        if "p01" not in fname or not fname.endswith(".pcap"):
            continue

        pcap_path = os.path.join(PCAP_DIR, fname)
        dt = load_clean_dt(pcap_path)
        if dt is None:
            print("[SKIP]", fname, "not enough streaming data")
            continue

        # select model config based on substring in filename
        cfg = None
        for key, meta in MODEL_CONFIG.items():
            if key.lower() in fname.lower():
                cfg = meta
                break

        if cfg is None:
            print("[WARN] no MODEL_CONFIG entry for", fname)
            continue

        x = np.arange(1, len(dt) + 1)  # token index starting at 1

        plt.plot(
            x,
            dt,
            label=cfg["label"],
            color=cfg["color"],
            linewidth=1.0,
        )

    plt.xlabel("Token Sequence")
    plt.ylabel("Time (seconds)")
    plt.ylim(bottom=0)
    plt.grid(True, alpha=0.3, linestyle="--")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=300)
    print("[OK] saved plot to", OUT_PNG)


if __name__ == "__main__":
    main()