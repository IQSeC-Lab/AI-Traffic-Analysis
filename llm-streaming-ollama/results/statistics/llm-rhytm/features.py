#!/usr/bin/env python3
import os
import json
import numpy as np
from scapy.all import rdpcap, TCP
from scipy.stats import entropy, skew, kurtosis

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
INPUT_DIR = "captures/"
OUTPUT_DIR = "json_data3/"
WINDOW_SIZE = 0.5   # seconds
STEP = 0.1          # seconds

# Map folder/model name -> (family, size_label)
# MODEL_META = {
#      "zephyr-7b-beta": ("mistral", "7B")
# }

MODEL_META = {
    # ========================
    # 14B MODELS
    # ========================

    # --- Qwen2.5-14B family ---
    "Qwen2.5-14B": ("qwen2.5", "14B"),
    "0x-lite": ("qwen2.5", "14B"),
    "Gauss-Opus-14B": ("qwen2.5", "14B"),
    "Evac-Opus-14B": ("qwen2.5", "14B"),
    "Zurich-14B": ("qwen2.5", "14B"),
    "Rombo-LLM-V2.5-Qwen-14b": ("qwen2.5", "14B"),
    "Qwen2.5-Coder-14B": ("qwen2.5", "14B"),

    # --- Qwen3-14B family ---
    "Qwen3-14B": ("qwen3", "14B"),
    "Qwen3-14B-MegaScience": ("qwen3", "14B"),
    "GrayLine-Qwen3-14B": ("qwen3", "14B"),

    # --- Nemotron 14B ---
    "AceReason-Nemotron-14B": ("nemotron", "14B"),


    # ========================
    # 7B MODELS
    # ========================

    # --- Qwen2.5-7B family ---
    "DeepHat-V1-7B": ("qwen2.5", "7B"),
    "Qwen2.5-7B": ("qwen2.5", "7B"),
    "AceReason-Nemotron-1.1-7B": ("qwen2.5", "7B"),

    # --- Monarch-7B family ---
    "Spaetzle-v60-7b": ("monarch", "7B"),

    # --- Mistral-7B family ---
    "NeuralDaredevil-7B": ("mistral", "7B"),
    "ghost-7b-alpha": ("mistral", "7B"),
    "GritLM-7B": ("mistral", "7B"),
    "Mistral-7B-Instruct": ("mistral", "7B"),
    "zephyr-7b-beta": ("mistral", "7B"),
    "neural-chat-7b": ("mistral", "7B"),
}

# -------------------------------------------------------------------
# LOW-LEVEL PACKET EXTRACTION
# -------------------------------------------------------------------
def extract_packet_series(pcap_file):
    """
    Read pcap and return:
      times: np.array of packet arrival timestamps (float)
      sizes: np.array of packet sizes in bytes (int)
      delta_t: np.array of inter-arrival times between packets
    Only TCP packets are considered; payload contents are irrelevant,
    so this works fine over HTTPS.
    """
    packets = rdpcap(pcap_file)

    # Keep only TCP packets (assume pcap already filtered to the LLM flow)
    data_pkts = [p for p in packets if TCP in p]

    if len(data_pkts) < 3:
        return None, None, None

    times = np.array([float(p.time) for p in data_pkts])
    sizes = np.array([len(p) for p in data_pkts])

    # Inter-arrival times between consecutive packets
    delta_t = np.diff(times)

    # Align all arrays to length N-1 so index i refers to the same packet
    # (packet i+1 relative to original times)
    times = times[1:]
    sizes = sizes[1:]

    return times, sizes, delta_t


# -------------------------------------------------------------------
# SLIDING WINDOWS
# -------------------------------------------------------------------
def sliding_windows(times, sizes, delta_t,
                    window_size=WINDOW_SIZE, step=STEP):
    """
    Return list of (dt_window, size_window) for each sliding time window.
    We mask on packet times; delta_t is aligned to times.
    """
    features = []

    if times is None or len(times) < 3:
        return features

    start = times[0]
    end = times[-1]
    current = start

    while current + window_size <= end:
        mask = (times >= current) & (times < current + window_size)
        idx = np.where(mask)[0]

        if len(idx) > 5:
            dt_window = delta_t[idx]
            size_window = sizes[idx]
            if len(dt_window) > 0:
                features.append((dt_window, size_window))

        current += step

    return features


# -------------------------------------------------------------------
# 36-D FEATURE VECTOR (CLOSE TO APPENDIX A)
# -------------------------------------------------------------------
def safe_stats(x):
    if len(x) == 0:
        return 0.0, 0.0, 0.0, 0.0
    return np.mean(x), np.std(x), np.min(x), np.max(x)


def compute_features(dt, sizes):
    """
    Compute one 36-D feature vector from a window of inter-arrival times
    (dt) and packet sizes (sizes), following the paper’s categories:
    rate-based, IAT stats, pattern/regularity, change/accel, correlation,
    entropy/burstiness.[file:31]
    """
    feats = []

    # Basic stats: inter-arrival times
    mean_dt, std_dt, min_dt, max_dt = safe_stats(dt)
    p25_dt = np.percentile(dt, 25) if len(dt) > 0 else 0.0
    p50_dt = np.percentile(dt, 50) if len(dt) > 0 else 0.0
    p75_dt = np.percentile(dt, 75) if len(dt) > 0 else 0.0
    skew_dt = skew(dt) if len(dt) > 2 else 0.0
    kurt_dt = kurtosis(dt) if len(dt) > 3 else 0.0

    feats.extend([
        mean_dt, std_dt, min_dt, max_dt,
        p25_dt, p50_dt, p75_dt,
        skew_dt, kurt_dt
    ])

    # Basic stats: sizes
    mean_sz, std_sz, min_sz, max_sz = safe_stats(sizes)
    p25_sz = np.percentile(sizes, 25) if len(sizes) > 0 else 0.0
    p50_sz = np.percentile(sizes, 50) if len(sizes) > 0 else 0.0
    p75_sz = np.percentile(sizes, 75) if len(sizes) > 0 else 0.0

    feats.extend([
        mean_sz, std_sz, min_sz, max_sz,
        p25_sz, p50_sz, p75_sz
    ])

    # Rate / throughput (packets per second in this window)
    duration = np.sum(dt)
    packet_rate = len(dt) / duration if duration > 0 else 0.0
    feats.append(packet_rate)

    # Burstiness (as in paper: based on mean/std of IAT).[file:31]
    if mean_dt + std_dt > 0:
        burstiness = (std_dt - mean_dt) / (std_dt + mean_dt + 1e-8)
    else:
        burstiness = 0.0
    feats.append(burstiness)

    # Entropy of dt and sizes (10 bins)
    if len(dt) > 1:
        hist_dt, _ = np.histogram(dt, bins=10, density=True)
        ent_dt = entropy(hist_dt + 1e-8)
    else:
        ent_dt = 0.0

    if len(sizes) > 1:
        hist_sz, _ = np.histogram(sizes, bins=10, density=True)
        ent_sz = entropy(hist_sz + 1e-8)
    else:
        ent_sz = 0.0

    feats.append(ent_dt)
    feats.append(ent_sz)

    # Timing dynamics: first diff of dt
    dt_diff = np.diff(dt)
    mean_dt_diff = np.mean(dt_diff) if len(dt_diff) > 0 else 0.0
    std_dt_diff = np.std(dt_diff) if len(dt_diff) > 0 else 0.0
    feats.extend([mean_dt_diff, std_dt_diff])

    # Acceleration (second diff)
    dt_acc = np.diff(dt_diff)
    mean_dt_acc = np.mean(dt_acc) if len(dt_acc) > 0 else 0.0
    feats.append(mean_dt_acc)

    # Correlation between dt and sizes
    if len(dt) > 1 and len(dt) == len(sizes):
        corr = np.corrcoef(dt, sizes)[0, 1]
        if np.isnan(corr):
            corr = 0.0
    else:
        corr = 0.0
    feats.append(corr)

    # Size–time interaction
    if len(dt) > 0:
        feats.append(np.mean(dt * sizes))
    else:
        feats.append(0.0)

    # Max burst rate (1 / min IAT)
    if len(dt) > 0:
        feats.append(float(np.max(1.0 / (dt + 1e-8))))
    else:
        feats.append(0.0)

    return np.asarray(feats, dtype=float)


# -------------------------------------------------------------------
# BUILD DATASET FOR ONE PCAP
# -------------------------------------------------------------------
def build_dataset(pcap_file, model_name):
    times, sizes, delta_t = extract_packet_series(pcap_file)

    if times is None:
        return []

    windows = sliding_windows(times, sizes, delta_t,
                              window_size=WINDOW_SIZE,
                              step=STEP)

    # map model_name to (family, size)
    key = None
    for k in MODEL_META:
        if k.lower() in model_name.lower():
            key = k
            break

    if key is None:
        raise ValueError(f"Unknown model in MODEL_META: {model_name}")

    family, size_label = MODEL_META[key]

    samples = []
    for dt_w, sz_w in windows:
        feat = compute_features(dt_w, sz_w)
        samples.append({
            "features": feat.tolist(),
            "family": family,        # optional
            "size": size_label,      # optional
            "model": model_name,     # 🔥 THIS IS YOUR LABEL
        })

    return samples


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for file in os.listdir(INPUT_DIR):
        if not file.endswith(".pcap"):
            continue

        pcap_path = os.path.join(INPUT_DIR, file)

        # derive model_name from filename
        # e.g., "HuggingFaceH4-zephyr-7b-beta-p01.pcap"
        base = os.path.splitext(file)[0]
        model_name = base

        # remove suffix like "-p01", "-p02", etc.
        if "-p" in model_name:
            model_name = model_name.split("-p")[0]

        try:
            samples = build_dataset(pcap_path, model_name)

            if not samples:
                print(f"[SKIP] {file} → no valid windows")
                continue

            out_file = os.path.join(
                OUTPUT_DIR,
                f"{model_name}_{base}.json"
            )

            with open(out_file, "w") as f:
                json.dump(samples, f)

            print(f"[OK] {out_file} → {len(samples)} samples")

        except Exception as e:
            print(f"[ERROR] {file}: {e}")

if __name__ == "__main__":
    main()