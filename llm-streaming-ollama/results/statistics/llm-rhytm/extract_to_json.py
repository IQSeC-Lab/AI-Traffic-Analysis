import os
import json
import numpy as np
from scapy.all import rdpcap, TCP
from scipy.stats import entropy, skew, kurtosis

# -----------------------------
# MODEL METADATA (EDITABLE)
# -----------------------------
MODEL_META = {
    # 7B
    "Qwen2.5-7B-Instruct": ("qwen", "7B"),
    "zephyr-7b-beta": ("mistral", "7B"),
    "Mistral-7B-Instruct-v0.2": ("mistral", "7B"),
    "neural-chat-7b-v3-3": ("intel", "7B"),
    "AceReason-Nemotron-1.1-7B": ("nvidia", "7B"),
    "GritLM-7B": ("other", "7B"),
    "NeuralDaredevil-7B": ("other", "7B"),
    "DeepHat-V1-7B": ("other", "7B"),
    "Spaetzle-v60-7b": ("other", "7B"),
    "ghost-7b-alpha": ("ghost", "7B"),

    # 14B
    "Gauss-Opus-14B-R999": ("other", "14B"),
    "Qwen3-14B-Base": ("qwen", "14B"),
    "0x-lite": ("other", "14B"),
    "AceReason-Nemotron-14B": ("nvidia", "14B"),
    "Qwen3-14B-MegaScience": ("qwen", "14B"),
    "GrayLine-Qwen3-14B": ("qwen", "14B"),
    "Evac-Opus-14B-Exp": ("other", "14B"),
    "Zurich-14B-GCv2-5m": ("other", "14B"),
    "Rombo-LLM-V2.5-Qwen-14b": ("qwen", "14B"),
    "Qwen2.5-Coder-14B-Instruct": ("qwen", "14B"),
}

# -----------------------------
# FEATURE EXTRACTION
# -----------------------------
def extract_packets(pcap):
    packets = rdpcap(pcap)
    data_pkts = [p for p in packets if TCP in p and len(p[TCP].payload) > 0]

    times = np.array([float(p.time) for p in data_pkts])
    sizes = np.array([len(p) for p in data_pkts])

    if len(times) < 2:
        return None, None

    dt = np.diff(times)
    return dt, sizes[:-1]


def compute_features(dt, sizes):
    feats = []

    feats.extend([
        np.mean(dt), np.std(dt), np.min(dt), np.max(dt),
        skew(dt), kurtosis(dt)
    ])

    feats.extend([
        np.mean(sizes), np.std(sizes)
    ])

    duration = np.sum(dt)
    feats.append(len(dt) / duration if duration > 0 else 0)

    hist, _ = np.histogram(dt, bins=10, density=True)
    feats.append(entropy(hist + 1e-8))

    return feats


# -----------------------------
# MAIN
# -----------------------------
def process_pcap(pcap_path, model_name):
    dt, sizes = extract_packets(pcap_path)
    if dt is None:
        return []

    window_size = 50   # number of samples (you can tune)
    step = 10

    samples = []

    # detect metadata
    key = None
    for k in MODEL_META:
        if k.lower() in model_name.lower():
            key = k
            break

    if key is None:
        raise ValueError(f"Unknown model: {model_name}")

    family, size = MODEL_META[key]

    for i in range(0, len(dt) - window_size, step):
        dt_w = dt[i:i+window_size]
        sizes_w = sizes[i:i+window_size]

        feats = compute_features(dt_w, sizes_w)

        samples.append({
            "features": feats,
            "model": model_name,
            "family": family,
            "size": size
        })

    return samples

def main():
    INPUT_DIR = "test/"
    OUTPUT_DIR = "json_data/"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for model_folder in os.listdir(INPUT_DIR):
        model_path = os.path.join(INPUT_DIR, model_folder)

        if not os.path.isdir(model_path):
            continue

        for file in os.listdir(model_path):
            if not file.endswith(".pcap"):
                continue

            full_path = os.path.join(model_path, file)

            try:
                samples = process_pcap(full_path, model_folder)

                if not samples:
                    continue

                out_file = os.path.join(
                    OUTPUT_DIR, f"{model_folder}_{file}.json"
                )

                with open(out_file, "w") as f:
                    json.dump(samples, f)

                print(f"Saved {out_file} ({len(samples)} samples)")

            except Exception as e:
                print(f"Error: {file} -> {e}")


if __name__ == "__main__":
    main()