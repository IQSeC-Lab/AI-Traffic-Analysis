#!/usr/bin/env python3
"""
Multi-Prompt Classification Feature Extractor
Extracts 36-D feature vectors from pcap files for prompt category inference.
Output: One JSON per model containing all prompts with category labels.
"""

import os
import json
import glob
import argparse
import numpy as np
from scapy.all import rdpcap, TCP
from scipy.stats import entropy, skew, kurtosis


# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
INPUT_DIR = "captures/"
OUTPUT_DIR = "json_data_prompts/"
WINDOW_SIZE = 0.5   # seconds
STEP = 0.1          # seconds


# -------------------------------------------------------------------
# PROMPT CATEGORIES (24 prompts → 6 categories)
# -------------------------------------------------------------------
PROMPT_CATEGORIES = {
    0: "summarization",
    1: "summarization",
    2: "summarization",
    3: "summarization",
    4: "code_generation",
    5: "code_generation",
    6: "code_generation",
    7: "code_generation",
    8: "math_reasoning",
    9: "math_reasoning",
    10: "math_reasoning",
    11: "math_reasoning",
    12: "adversarial",
    13: "adversarial",
    14: "adversarial",
    15: "adversarial",
    16: "logical_puzzles",
    17: "logical_puzzles",
    18: "logical_puzzles",
    19: "logical_puzzles",
    20: "technical_explanation",
    21: "technical_explanation",
    22: "technical_explanation",
    23: "technical_explanation",
}


# -------------------------------------------------------------------
# PACKET EXTRACTION
# -------------------------------------------------------------------
def extract_packet_series(pcap_file):
    """
    Read pcap and return:
      times: np.array of packet arrival timestamps (float)
      sizes: np.array of packet sizes in bytes (int)
      delta_t: np.array of inter-arrival times between packets
    Only TCP packets are considered.
    """
    packets = rdpcap(pcap_file)
    data_pkts = [p for p in packets if TCP in p]

    if len(data_pkts) < 3:
        return None, None, None

    times = np.array([float(p.time) for p in data_pkts])
    sizes = np.array([len(p) for p in data_pkts])
    delta_t = np.diff(times)

    # Align all arrays to length N-1
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
# 36-D FEATURE VECTOR
# -------------------------------------------------------------------
def safe_stats(x):
    if len(x) == 0:
        return 0.0, 0.0, 0.0, 0.0
    return np.mean(x), np.std(x), np.min(x), np.max(x)


def compute_features(dt, sizes):
    """
    Compute one 36-D feature vector from a window of inter-arrival times
    (dt) and packet sizes (sizes).

    Feature categories:
    - IAT stats: 9 features
    - Size stats: 7 features
    - Rate: 1 feature
    - Burstiness: 1 feature
    - Entropy: 2 features
    - Dynamics: 3 features
    - Correlation: 1 feature
    - Interaction: 1 feature
    - Max burst rate: 1 feature
    """
    feats = []

    # IAT stats (9 features)
    mean_dt, std_dt, min_dt, max_dt = safe_stats(dt)
    feats.extend([
        mean_dt, std_dt, min_dt, max_dt,
        np.percentile(dt, 25) if len(dt) > 0 else 0.0,
        np.percentile(dt, 50) if len(dt) > 0 else 0.0,
        np.percentile(dt, 75) if len(dt) > 0 else 0.0,
        skew(dt) if len(dt) > 2 else 0.0,
        kurtosis(dt) if len(dt) > 3 else 0.0,
    ])

    # Size stats (7 features)
    mean_sz, std_sz, min_sz, max_sz = safe_stats(sizes)
    feats.extend([
        mean_sz, std_sz, min_sz, max_sz,
        np.percentile(sizes, 25) if len(sizes) > 0 else 0.0,
        np.percentile(sizes, 50) if len(sizes) > 0 else 0.0,
        np.percentile(sizes, 75) if len(sizes) > 0 else 0.0,
    ])

    # Rate (1 feature)
    duration = np.sum(dt)
    feats.append(len(dt) / duration if duration > 0 else 0.0)

    # Burstiness (1 feature)
    if mean_dt + std_dt > 0:
        feats.append((std_dt - mean_dt) / (std_dt + mean_dt + 1e-8))
    else:
        feats.append(0.0)

    # Entropy (2 features)
    if len(dt) > 1:
        hist_dt, _ = np.histogram(dt, bins=10, density=True)
        feats.append(entropy(hist_dt + 1e-8))
    else:
        feats.append(0.0)

    if len(sizes) > 1:
        hist_sz, _ = np.histogram(sizes, bins=10, density=True)
        feats.append(entropy(hist_sz + 1e-8))
    else:
        feats.append(0.0)

    # Dynamics (3 features)
    dt_diff = np.diff(dt)
    feats.extend([
        np.mean(dt_diff) if len(dt_diff) > 0 else 0.0,
        np.std(dt_diff) if len(dt_diff) > 0 else 0.0,
    ])
    dt_acc = np.diff(dt_diff)
    feats.append(np.mean(dt_acc) if len(dt_acc) > 0 else 0.0)

    # Correlation (1 feature)
    if len(dt) > 1 and len(dt) == len(sizes):
        corr = np.corrcoef(dt, sizes)[0, 1]
        feats.append(0.0 if np.isnan(corr) else corr)
    else:
        feats.append(0.0)

    # Interaction (1 feature)
    feats.append(np.mean(dt * sizes) if len(dt) > 0 else 0.0)

    # Max burst rate (1 feature)
    feats.append(np.max(1.0 / (dt + 1e-8)) if len(dt) > 0 else 0.0)

    return np.asarray(feats, dtype=float)


# -------------------------------------------------------------------
# FILENAME PARSING
# -------------------------------------------------------------------
def parse_filename(filename):
    """
    Parse filename like: model-name-p01.pcap
    Returns: (model_name, prompt_idx)
    """
    base = os.path.splitext(filename)[0]

    prompt_idx = -1
    model_name = base

    if "-p" in base:
        parts = base.rsplit("-p", 1)
        model_name = parts[0]
        try:
            prompt_idx = int(parts[1])
        except ValueError:
            pass

    return model_name, prompt_idx


# -------------------------------------------------------------------
# DATASET BUILDER
# -------------------------------------------------------------------
def build_dataset(pcap_file, model_name, prompt_idx):
    """
    Build dataset samples from a single pcap file.
    Returns list of dicts with features and labels.
    """
    times, sizes, delta_t = extract_packet_series(pcap_file)

    if times is None:
        return []

    windows = sliding_windows(times, sizes, delta_t)
    prompt_category = PROMPT_CATEGORIES.get(prompt_idx, "unknown")

    samples = []
    for dt_w, sz_w in windows:
        feat = compute_features(dt_w, sz_w)
        samples.append({
            "features": feat.tolist(),
            "prompt_idx": prompt_idx,
            "prompt_category": prompt_category,
            "model_name": model_name,
        })

    return samples


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Extract features from pcap files for prompt classification"
    )
    parser.add_argument(
        "--input", "-i",
        default=INPUT_DIR,
        help=f"Input directory containing pcap files (default: {INPUT_DIR})"
    )
    parser.add_argument(
        "--output", "-o",
        default=OUTPUT_DIR,
        help=f"Output directory for JSON files (default: {OUTPUT_DIR})"
    )
    parser.add_argument(
        "--per-prompt",
        action="store_true",
        help="Output one JSON per prompt instead of one per model"
    )
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    if args.per_prompt:
        # One JSON per prompt (480 files for 20 models × 24 prompts)
        for file in sorted(os.listdir(args.input)):
            if not file.endswith(".pcap"):
                continue

            pcap_path = os.path.join(args.input, file)
            model_name, prompt_idx = parse_filename(file)

            try:
                samples = build_dataset(pcap_path, model_name, prompt_idx)

                if not samples:
                    print(f"[SKIP] {file} → no valid windows")
                    continue

                safe_name = model_name.replace("/", "_").replace("\\", "_")
                out_file = os.path.join(
                    args.output,
                    f"{safe_name}_p{prompt_idx:02d}.json"
                )

                with open(out_file, "w") as f:
                    json.dump(samples, f)

                print(f"[OK] {out_file} → {len(samples)} samples")

            except Exception as e:
                print(f"[ERROR] {file}: {e}")

    else:
        # One JSON per model (20 files)
        model_datasets = {}

        for file in sorted(os.listdir(args.input)):
            if not file.endswith(".pcap"):
                continue

            pcap_path = os.path.join(args.input, file)
            model_name, prompt_idx = parse_filename(file)

            try:
                samples = build_dataset(pcap_path, model_name, prompt_idx)

                if not samples:
                    print(f"[SKIP] {file} → no valid windows")
                    continue

                if model_name not in model_datasets:
                    model_datasets[model_name] = []

                model_datasets[model_name].extend(samples)
                print(f"[OK] {file} → {len(samples)} windows (prompt {prompt_idx})")

            except Exception as e:
                print(f"[ERROR] {file}: {e}")

        # Write one consolidated JSON per model
        for model_name, samples in model_datasets.items():
            safe_name = model_name.replace("/", "_").replace("\\", "_")
            out_file = os.path.join(args.output, f"{safe_name}_prompts.json")

            with open(out_file, "w") as f:
                json.dump(samples, f)

            print(f"[WRITE] {out_file} → {len(samples)} total samples")

            # Print category distribution
            categories = {}
            for s in samples:
                cat = s["prompt_category"]
                categories[cat] = categories.get(cat, 0) + 1
            print(f"  Distribution: {categories}")


if __name__ == "__main__":
    main()
