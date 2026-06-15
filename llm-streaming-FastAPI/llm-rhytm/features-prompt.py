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
OUTPUT_DIR = "json_data_prompts/"
WINDOW_SIZE = 0.5
STEP = 0.1
SERVER_PORT = 8000  # Ollama default, adjust as needed

# -------------------------------------------------------------------
# PROMPT CATEGORIES
# -------------------------------------------------------------------
PROMPT_CATEGORIES = {
    0: "summarization", 1: "summarization", 2: "summarization", 3: "summarization",
    4: "code_generation", 5: "code_generation", 6: "code_generation", 7: "code_generation",
    8: "math_reasoning", 9: "math_reasoning", 10: "math_reasoning", 11: "math_reasoning",
    12: "adversarial", 13: "adversarial", 14: "adversarial", 15: "adversarial",
    16: "logical_puzzles", 17: "logical_puzzles", 18: "logical_puzzles", 19: "logical_puzzles",
    20: "technical_explanation", 21: "technical_explanation", 22: "technical_explanation", 23: "technical_explanation",
}

# -------------------------------------------------------------------
# PACKET EXTRACTION WITH DIRECTION
# -------------------------------------------------------------------
def extract_packet_series(pcap_file, server_port=SERVER_PORT):
    packets = rdpcap(pcap_file)
    data_pkts = [p for p in packets if TCP in p]
    
    if len(data_pkts) < 3:
        return None, None, None, None
    
    times = np.array([float(p.time) for p in data_pkts])
    sizes = np.array([len(p) for p in data_pkts])
    
    # Direction: 1 = client->server (request), -1 = server->client (response)
    directions = np.array([
        1 if p[TCP].sport != server_port and p[TCP].dport == server_port else -1
        for p in data_pkts
    ])
    
    delta_t = np.diff(times)
    return times[1:], sizes[1:], delta_t, directions[1:]

# -------------------------------------------------------------------
# SLIDING WINDOWS (FIXED INDEXING)
# -------------------------------------------------------------------
def sliding_windows(times, sizes, delta_t, directions):
    features = []
    
    if times is None or len(times) < 3:
        return features
    
    start = times[0]
    end = times[-1]
    current = start
    
    while current + WINDOW_SIZE <= end:
        mask = (times >= current) & (times < current + WINDOW_SIZE)
        idx = np.where(mask)[0]
        
        if len(idx) > 5:
            # FIXED: delta_t index j corresponds to times[j+1]
            dt_idx = idx[idx > 0] - 1
            dt_window = delta_t[dt_idx]
            size_window = sizes[idx]
            dir_window = directions[idx] if directions is not None else None
            
            if len(dt_window) > 0:
                features.append((dt_window, size_window, dir_window))
        
        current += STEP
    
    return features

# -------------------------------------------------------------------
# FEATURE ENGINEERING (WITH DIRECTIONAL FEATURES)
# -------------------------------------------------------------------
def safe_stats(x):
    if len(x) == 0:
        return 0.0, 0.0, 0.0, 0.0
    return np.mean(x), np.std(x), np.min(x), np.max(x)

def compute_features(dt, sizes, directions):
    feats = []
    
    # Basic timing stats (all traffic)
    mean_dt, std_dt, min_dt, max_dt = safe_stats(dt)
    feats.extend([mean_dt, std_dt, min_dt, max_dt])
    
    feats.extend([
        np.percentile(dt, 25) if len(dt) > 0 else 0.0,
        np.percentile(dt, 50) if len(dt) > 0 else 0.0,
        np.percentile(dt, 75) if len(dt) > 0 else 0.0,
        skew(dt) if len(dt) > 2 else 0.0,
        kurtosis(dt) if len(dt) > 3 else 0.0,
    ])
    
    # Basic size stats (all traffic)
    mean_sz, std_sz, min_sz, max_sz = safe_stats(sizes)
    feats.extend([mean_sz, std_sz, min_sz, max_sz])
    
    feats.extend([
        np.percentile(sizes, 25) if len(sizes) > 0 else 0.0,
        np.percentile(sizes, 50) if len(sizes) > 0 else 0.0,
        np.percentile(sizes, 75) if len(sizes) > 0 else 0.0,
    ])
    
    # Rate
    duration = np.sum(dt)
    feats.append(len(dt) / duration if duration > 0 else 0.0)
    
    # Burstiness
    if mean_dt + std_dt > 0:
        feats.append((std_dt - mean_dt) / (std_dt + mean_dt + 1e-8))
    else:
        feats.append(0.0)
    
    # Entropy
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
    
    # Dynamics
    dt_diff = np.diff(dt)
    feats.extend([
        np.mean(dt_diff) if len(dt_diff) > 0 else 0.0,
        np.std(dt_diff) if len(dt_diff) > 0 else 0.0,
    ])
    
    dt_acc = np.diff(dt_diff)
    feats.append(np.mean(dt_acc) if len(dt_acc) > 0 else 0.0)
    
    # Correlation
    if len(dt) > 1 and len(dt) == len(sizes):
        corr = np.corrcoef(dt, sizes)[0, 1]
        feats.append(0.0 if np.isnan(corr) else corr)
    else:
        feats.append(0.0)
    
    # Interaction
    feats.append(np.mean(dt * sizes) if len(dt) > 0 else 0.0)
    
    # Max burst rate
    feats.append(np.max(1.0 / (dt + 1e-8)) if len(dt) > 0 else 0.0)
    
    # NEW: Directional features (key for prompt category inference)
    if directions is not None:
        resp_mask = directions == -1  # server -> client
        req_mask = directions == 1     # client -> server
        
        resp_sizes = sizes[resp_mask]
        req_sizes = sizes[req_mask]
        
        # Response size stats (prompt-dependent output)
        mean_resp, std_resp, _, max_resp = safe_stats(resp_sizes)
        feats.extend([mean_resp, std_resp, max_resp])
        
        # Request/response ratio
        total_resp = np.sum(resp_sizes) if len(resp_sizes) > 0 else 0
        total_req = np.sum(req_sizes) if len(req_sizes) > 0 else 1
        feats.append(total_resp / total_req)
        
        # Response-specific timing (token generation pattern)
        resp_indices = np.where(resp_mask)[0]
        if len(resp_indices) > 1:
            resp_dt = dt[resp_indices[1:] - 1]  # careful indexing
            feats.extend([
                np.std(resp_dt) / (np.mean(resp_dt) + 1e-8),
                np.percentile(resp_sizes, 90) if len(resp_sizes) > 0 else 0.0,
                np.percentile(resp_sizes, 95) if len(resp_sizes) > 0 else 0.0,
            ])
        else:
            feats.extend([0.0, 0.0, 0.0])
        
        # Response packet count ratio
        feats.append(len(resp_sizes) / (len(sizes) + 1e-8))
    
    return np.asarray(feats, dtype=float)

# -------------------------------------------------------------------
# FILENAME PARSING (WITH MODEL ID)
# -------------------------------------------------------------------
def parse_filename(filename):
    base = os.path.splitext(filename)[0]
    model_id = None
    prompt_idx = -1
    
    if "-p" in base:
        model_part, prompt_part = base.rsplit("-p", 1)
        model_id = model_part
        try:
            prompt_idx = int(prompt_part)
        except:
            pass
    
    return model_id, prompt_idx

# -------------------------------------------------------------------
# DATASET BUILDER
# -------------------------------------------------------------------
def build_dataset(pcap_file, prompt_idx, model_id=None):
    times, sizes, delta_t, directions = extract_packet_series(pcap_file)
    
    if times is None:
        return []
    
    windows = sliding_windows(times, sizes, delta_t, directions)
    prompt_category = PROMPT_CATEGORIES.get(prompt_idx, "unknown")
    
    samples = []
    for dt_w, sz_w, dir_w in windows:
        feat = compute_features(dt_w, sz_w, dir_w)
        
        samples.append({
            "features": feat.tolist(),
            "prompt_idx": prompt_idx,
            "prompt_category": prompt_category,
            "model_id": model_id,
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
        model_id, prompt_idx = parse_filename(file)
        
        try:
            samples = build_dataset(pcap_path, prompt_idx, model_id)
            
            if not samples:
                print(f"[SKIP] {file}")
                continue
            
            # Include model in output filename for organization
            out_file = os.path.join(
                OUTPUT_DIR,
                f"{model_id}_p{prompt_idx}.json" if model_id else f"prompt_p{prompt_idx}.json"
            )
            
            with open(out_file, "w") as f:
                json.dump(samples, f)
            
            print(f"[OK] {out_file} → {len(samples)} samples")
            
        except Exception as e:
            print(f"[ERROR] {file}: {e}")

if __name__ == "__main__":
    main()