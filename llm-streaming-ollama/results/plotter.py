import json, glob, os, re
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Config ────────────────────────────────────────────────────────────────
LOG_DIR = "./logs"        # path to your JSON log files
PATTERN = "*-p02.json"        # glob filter, e.g. "*-p01.json" for a single prompt
OUTPUT  = "itt_multimodel.png"
# ─────────────────────────────────────────────────────────────────────────

COLORS = {
    "Gemma2 9B":   "#1f77b4",
    "Gemma 2B":    "#ff7f0e",
    "LLaMA2 7B":   "#2ca02c",
    "LLaMA3.2 3B": "#d62728",
    "LLaMA3 8B":   "#9467bd",
    "Mistral 7B":  "#e377c2",
}

def load_itts(path):
    with open(path) as f:
        data = json.load(f)
    timing = data.get("timing", [])
    if len(timing) < 2:
        return None
    times = [e["t"] for e in timing]
    return [times[i+1] - times[i] for i in range(len(times) - 1)]

def clean_model_name(basename):
    name = re.sub(r"[-_]p\d+$", "", basename)          # strip -p01 / _p02
    return name.replace("-", " ").replace("_", " ").title()

# ── Aggregate ITTs per model across all prompt files ──────────────────────
model_data = {}
for fpath in sorted(glob.glob(os.path.join(LOG_DIR, PATTERN))):
    itts = load_itts(fpath)
    if itts is None:
        continue
    model = clean_model_name(os.path.splitext(os.path.basename(fpath))[0])
    model_data.setdefault(model, []).extend(itts)

# ── Plot ──────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 6))
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

for model, itts in model_data.items():
    ax.plot(range(len(itts)), itts,
            linewidth=0.8, alpha=0.9,
            label=model,
            color=COLORS.get(model))

ax.grid(True, linestyle="--", linewidth=0.5, color="#cccccc", alpha=0.7)
ax.set_axisbelow(True)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.tick_params(labelsize=10)

ax.legend(ncol=2, loc="upper right", fontsize=10,
          frameon=True, framealpha=1.0, edgecolor="#cccccc",
          handlelength=1.5, handletextpad=0.5)

plt.tight_layout()
plt.savefig(OUTPUT, dpi=150, bbox_inches="tight")
plt.close()
print(f"Saved → {OUTPUT}")