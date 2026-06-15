#!/usr/bin/env python3
import os
import numpy as np
import matplotlib.pyplot as plt
from scapy.all import rdpcap, TCP
import re

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
PCAP_DIR    = "captures/"   # folder with *-p01.pcap files
OUT_PNG     = "itt_p01_400_multi_models.png"
MAX_POINTS  = 400            # length of token sequence
BIG_GAP_SEC = 0.3            # threshold to detect TTFT / big stall

# Map unique substrings in filenames -> label + color
# MODEL_CONFIG = {
#     "nvidia-AceReason-Nemotron-14B": {
#         "label": "Nemotron 14B",
#         "color": "#1f77b4",  # blue
#     },
#     "Qwen-Qwen3-14B-Base": {
#         "label": "Qwen3 14B Base",
#         "color": "#ff7f0e",  # orange
#     },
#     "rubenroy-Zurich-14B-GCV2-5m": {
#         "label": "Zurich 14B GCV2-5m",
#         "color": "#2ca02c",  # green
#     },
#     # add more models here as needed
# }
MODEL_CONFIG = {
    # ========================
    # 14B MODELS
    # ========================
    "nvidia-AceReason-Nemotron-14B": {
        "label": "Nemotron 14B",
        "color": "#1f77b4",
    },
    "Qwen-Qwen3-14B-Base": {
        "label": "Qwen3 14B Base",
        "color": "#ff7f0e",
    },
    "MegaScience-Qwen3-14B-MegaScience": {
        "label": "Qwen3 14B MegaScience",
        "color": "#9467bd",
    },
    "soob3123-GrayLine-Qwen3-14B": {
        "label": "GrayLine Qwen3 14B",
        "color": "#8c564b",
    },
    "rubenroy-Zurich-14B-GCV2-5m": {
        "label": "Zurich 14B GCV2",
        "color": "#2ca02c",
    },
    "ozone-research-0x-lite": {
        "label": "0x-lite 14B",
        "color": "#e377c2",
    },
    "prithivMLmods-Gauss-Opus-14B-R999": {
        "label": "Gauss Opus 14B",
        "color": "#7f7f7f",
    },
    "prithivMLmods-Evac-Opus-14B-Exp": {
        "label": "Evac Opus 14B",
        "color": "#bcbd22",
    },
    "unsloth-Qwen2.5-Coder-14B-Instruct": {
        "label": "Qwen2.5 Coder 14B",
        "color": "#17becf",
    },
    "Rombo-Org-Rombo-LLM-V2.5-Qwen-14b": {
        "label": "Rombo Qwen 14B",
        "color": "#aec7e8",
    },

    # ========================
    # 7B MODELS
    # ========================
    "mlabonne-NeuralDaredevil-7B": {
        "label": "NeuralDaredevil 7B",
        "color": "#ff9896",
    },
    "DeepHat-DeepHat-V1-7B": {
        "label": "DeepHat 7B",
        "color": "#98df8a",
    },
    "Intel-neural-chat-7b-v3-3": {
        "label": "Intel Neural Chat 7B",
        "color": "#c5b0d5",
    },
    "mistralai-Mistral-7B-Instruct-v0.2": {
        "label": "Mistral 7B Instruct",
        "color": "#c49c94",
    },
    "cstr-Spaetzle-v60-7b": {
        "label": "Spaetzle 7B",
        "color": "#f7b6d2",
    },
    "HuggingFaceH4-zephyr-7b-beta": {
        "label": "Zephyr 7B Beta",
        "color": "#dbdb8d",
    },
    "GritLM-GritLM-7B": {
        "label": "GritLM 7B",
        "color": "#9edae5",
    },
    "Qwen-Qwen2.5-7B-Instruct": {
        "label": "Qwen2.5 7B Instruct",
        "color": "#393b79",
    },
    "ghost-x-ghost-7b-alpha": {
        "label": "Ghost 7B Alpha",
        "color": "#637939",
    },
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
        def normalize_name(name):
            name = name.lower()
            name = re.sub(r"-p\d+\.pcap$", "", name)  # remove -p01.pcap
            return name

        fname_norm = normalize_name(fname)

        cfg = None
        for key, meta in MODEL_CONFIG.items():
            if key.lower() == fname_norm:
                cfg = meta
                break
        
        # cfg = None
        # for key, meta in MODEL_CONFIG.items():
        #     if key.lower() in fname.lower():
        #         cfg = meta
        #         break

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