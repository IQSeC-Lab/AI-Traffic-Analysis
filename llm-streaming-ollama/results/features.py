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

# Canonical short names (lowercase, no -pXX) → (family, size_label)
MODEL_META = {
    "gemma-2b":    ("gemma",   "2B"),
    "gemma2-2b":   ("gemma2",  "2B"),
    "gemma-7b":    ("gemma",   "7B"),
    "gemma2-9b":   ("gemma2",  "9B"),
    "llama2-7b":   ("llama2",  "7B"),
    "llama3.2-3b": ("llama3.2","3B"),
    "llama3-8b":   ("llama3",  "8B"),
    "mistral-7b":  ("mistral", "7B"),
}

# Pretty labels that match your COLORS dict
PRETTY_NAME = {
    "gemma-2b":    "Gemma 2B",
    "gemma2-2b":   "Gemma2 2B",
    "gemma-7b":    "Gemma 7B",
    "gemma2-9b":   "Gemma2 9B",
    "llama2-7b":   "LLaMA2 7B",
    "llama3.2-3b": "LLaMA3.2 3B",
    "llama3-8b":   "LLaMA3 8B",
    "mistral-7b":  "Mistral 7B",
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
    Only TCP packets are considered; payload contents are irrelevant.
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

        # relaxed threshold so short traces still produce windows
        if len(idx) > 2:
            dt_window = delta_t[idx]
            size_window = sizes[idx]
            if len(dt_window) > 0:
                features.append((dt_window, size_window))

        current += step

    # if still empty, fall back to one whole-flow window
    if not features and len(times) > 2:
        dt_window = delta_t
        size_window = sizes
        features.append((dt_window, size_window))

    return features


# -------------------------------------------------------------------
# 36-D FEATURE VECTOR
# -------------------------------------------------------------------
def safe_stats(x):
    if len(x) == 0:
        return 0.0, 0.0, 0.0, 0.0
    return np.mean(x), np.std(x), np.min(x), np.max(x)


def compute_features(dt, sizes):
    """
    Compute one feature vector from a window of inter-arrival times
    (dt) and packet sizes (sizes).
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

    # Burstiness
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

    key = model_name  # model_name is already canonical (no -pXX, lowercase)
    if key not in MODEL_META:
        raise ValueError(f"Unknown model in MODEL_META: {model_name}")

    family, size_label = MODEL_META[key]
    pretty = PRETTY_NAME.get(key, model_name)

    samples = []
    for dt_w, sz_w in windows:
        feat = compute_features(dt_w, sz_w)
        samples.append({
            "features": feat.tolist(),
            "family": pretty,      # used for COLORS in plotting
            "size": size_label,
            "model": model_name,
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
        base = os.path.splitext(file)[0]          # e.g. "gemma2-2b-p10"
        base_lower = base.lower()

        # Strip trailing -pXX (p01..p24 etc.) to get canonical model_name
        parts = base_lower.split("-p")
        if len(parts) >= 2 and parts[-1].isdigit():
            model_name = "-".join(parts[:-1])     # "gemma2-2b"
        else:
            model_name = base_lower               # fallback

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