"""
Analytics for capture runs, of every experiment.

Each capture yields one record that combines
  - the PCAP                         captures/<stem>.pcap
  - the client's per-event timing    results/<stem>.json  (runs from before this existed have none)
Records are cached in analysis/<stem>.json and rebuilt when the PCAP changes.
A capture's stem is <variant key>-p<index>, so a run's captures are grouped by the
variant (temperature, model, network condition) they were made with.

The "stream" is the TCP connection that carried the SSE response: of all the
flows from the inference server's port, the one with the most payload bytes.
The client's /health polls use the same port but carry far less data.
"""

from __future__ import annotations

import json
import math
import struct
import threading
from collections import Counter
from functools import lru_cache
from pathlib import Path
from statistics import median

from prompt_library import store as prompt_library

from .base import PROMPTS_FILE, Variant

SERVER_PORT = 8000
CACHE_VERSION = 3
UNCATEGORIZED = "Uncategorized"

# Inter-packet gaps are binned on a log scale: 10 bins per decade, 0.01 ms to 100 s.
GAP_EDGES_MS = [10 ** (k / 10) for k in range(-20, 51)]


# =============================================================================
# PCAP reading (classic libpcap format, as written by tcpdump -w)
# =============================================================================

_PCAP_MAGIC = {
    b"\xd4\xc3\xb2\xa1": ("<", 1e-6),
    b"\x4d\x3c\xb2\xa1": ("<", 1e-9),
    b"\xa1\xb2\xc3\xd4": (">", 1e-6),
    b"\xa1\xb2\x3c\x4d": (">", 1e-9),
}


def read_packets(path: Path) -> list[tuple[float, int, int, int, int]]:
    """(timestamp, src port, dst port, TCP payload bytes, frame bytes) for every TCP packet."""
    data = path.read_bytes()
    if len(data) < 24:
        return []
    if data[:4] not in _PCAP_MAGIC:
        raise ValueError(f"{path.name} is not a libpcap file")
    endian, frac = _PCAP_MAGIC[data[:4]]
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    record = struct.Struct(endian + "IIII")

    packets = []
    pos = 24
    while pos + 16 <= len(data):
        sec, sub, incl, orig = record.unpack_from(data, pos)
        pos += 16
        frame = data[pos:pos + incl]
        pos += incl
        if len(frame) < incl:   # truncated last record (tcpdump stopped mid-write)
            break
        tcp = _tcp_ports_and_payload(frame, linktype)
        if tcp:
            packets.append((sec + sub * frac, *tcp, orig))
    return packets


def _tcp_ports_and_payload(frame: bytes, linktype: int) -> tuple[int, int, int] | None:
    if linktype == 1:           # Ethernet
        offset, ethertype = 14, frame[12:14]
        if ethertype == b"\x81\x00":   # VLAN tag
            offset, ethertype = 18, frame[16:18]
    elif linktype == 113:       # Linux cooked capture
        offset, ethertype = 16, frame[14:16]
    else:
        return None

    ip = frame[offset:]
    if ethertype == b"\x08\x00" and len(ip) >= 20 and ip[9] == 6:        # IPv4 / TCP
        ip_header = (ip[0] & 0x0F) * 4
        segment_len = int.from_bytes(ip[2:4], "big") - ip_header
        tcp = ip[ip_header:]
    elif ethertype == b"\x86\xdd" and len(ip) >= 40 and ip[6] == 6:     # IPv6 / TCP
        segment_len = int.from_bytes(ip[4:6], "big")
        tcp = ip[40:]
    else:
        return None
    if len(tcp) < 20:
        return None
    tcp_header = (tcp[12] >> 4) * 4
    return (
        int.from_bytes(tcp[0:2], "big"),
        int.from_bytes(tcp[2:4], "big"),
        max(0, segment_len - tcp_header),
    )


# =============================================================================
# Per-capture records
# =============================================================================


def _prompt_and_iteration(index: int) -> tuple[int, int | None]:
    # Repeated runs use index = prompt * 1000 + iteration (see Experiment._units)
    return (index // 1000, index % 1000) if index >= 1000 else (index, None)


@lru_cache(maxsize=64)
def _load_run_prompts(path: str, mtime_ns: int) -> dict[int, dict]:
    return {int(n): p for n, p in json.loads(Path(path).read_text()).items()}


def run_prompts(run_dir: Path) -> dict[int, dict] | None:
    """The prompts the run was created with ({number: {"text", "category"}}), or None for
    runs saved before they were kept. Those took their prompts from the prompt library."""
    path = run_dir / PROMPTS_FILE
    try:
        return _load_run_prompts(str(path), path.stat().st_mtime_ns)
    except (OSError, ValueError, AttributeError):
        return None


def _known_prompt(run_dir: Path, number: int) -> dict | None:
    """A prompt of the run, from its own prompts. Only runs without them fall back to the
    library: in a Custom Prompts run, prompt 1 is not the library's prompt 1."""
    prompts = run_prompts(run_dir)
    return prompts.get(number) if prompts is not None else prompt_library.get(number)


def _identity(run_dir: Path, index: int, result: dict) -> tuple[int, int | None, str]:
    """Prompt number, iteration and category of a capture. Runs save them with the client's
    result; otherwise they come from the file index and the run's prompts."""
    if "prompt" in result:
        prompt, iteration = result["prompt"], result.get("iteration")
    else:
        prompt, iteration = _prompt_and_iteration(index)
    category = result.get("category")
    if not category:
        known = _known_prompt(run_dir, prompt)
        category = known["category"] if known else None
    return prompt, iteration, category or UNCATEGORIZED


def _gap_histogram(gaps_ms: list[float]) -> list[int]:
    counts = [0] * (len(GAP_EDGES_MS) - 1)
    lo, step = math.log10(GAP_EDGES_MS[0]), 0.1
    for gap in gaps_ms:
        i = int((math.log10(max(gap, 1e-9)) - lo) / step)
        counts[min(max(i, 0), len(counts) - 1)] += 1
    return counts


def _stream(packets: list[tuple]) -> list[tuple]:
    """Server → client packets with payload on the connection that carried the response."""
    down = [p for p in packets if p[1] == SERVER_PORT and p[3] > 0]
    if not down:
        return []
    per_flow = Counter()
    for p in down:
        per_flow[p[2]] += p[3]
    client_port = per_flow.most_common(1)[0][0]
    return [p for p in down if p[2] == client_port]


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


def build_record(pcap: Path, result_file: Path, index: int) -> dict:
    packets = read_packets(pcap)
    stream = _stream(packets)
    sizes = [p[3] for p in stream]
    gaps = [(b[0] - a[0]) * 1000 for a, b in zip(stream, stream[1:])]

    result = json.loads(result_file.read_text()) if result_file.exists() else {}
    prompt, iteration, category = _identity(pcap.parent.parent, index, result)
    record = {
        "version": CACHE_VERSION,
        "index": index,
        "prompt": prompt,
        "iteration": iteration,
        "category": category,
        # Which worker (and GPU) captured it, on runs with several workers
        "worker": result.get("worker"),
        "gpus": result.get("gpus"),
        "metrics": {
            "packets": len(packets),
            "bytes": sum(p[4] for p in packets),
            "capture_s": packets[-1][0] - packets[0][0] if packets else 0,
            "stream_packets": len(stream),
            "stream_bytes": sum(sizes),
            "stream_s": stream[-1][0] - stream[0][0] if stream else 0,
            "median_packet_bytes": _median(sizes),
            "median_gap_ms": _median(gaps),
            # From the client's timing (None when the run has no results file)
            "events": None,
            "ttft_ms": None,
            "duration_s": None,
            "events_per_s": None,
            "response_chars": None,
        },
        "size_counts": dict(Counter(sizes)),
        "gap_hist": _gap_histogram(gaps),
    }

    if result:
        timing = result.get("timing") or []
        m = record["metrics"]
        m["events"] = len(timing)
        m["response_chars"] = len(result.get("response") or "")
        if timing:
            m["ttft_ms"] = timing[0]["t"] * 1000
            m["duration_s"] = timing[-1]["t"]
            if m["duration_s"] > 0:
                m["events_per_s"] = len(timing) / m["duration_s"]
    return record


def capture_record(run_dir: Path, stem: str, index: int, build=None) -> dict:
    """The capture's record, from the cache when the PCAP hasn't changed since. `build` makes
    the record of another kind of capture (marble_analysis.py); it takes what build_record does."""
    pcap = run_dir / "captures" / f"{stem}.pcap"
    result_file = run_dir / "results" / f"{stem}.json"
    cache = run_dir / "analysis" / f"{stem}.json"
    key = [pcap.stat().st_mtime_ns, pcap.stat().st_size, result_file.exists()]
    try:
        cached = json.loads(cache.read_text())
        if cached.get("version") == CACHE_VERSION and cached.get("key") == key:
            return cached
    except (OSError, ValueError):
        pass
    try:
        record = (build or build_record)(pcap, result_file, index)
    except (OSError, ValueError, struct.error) as e:
        prompt, iteration, category = _identity(run_dir, index, {})
        record = {"version": CACHE_VERSION, "index": index, "prompt": prompt, "iteration": iteration,
                  "category": category, "worker": None, "gpus": None, "error": str(e), "metrics": {}, "size_counts": {},
                  "gap_hist": [0] * (len(GAP_EDGES_MS) - 1)}
    record["key"] = key
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(record))
    return record


def _captures(run_dir: Path, variants: list[Variant]) -> list[tuple[str, int, str]]:
    """(file stem, index, variant key) for each PCAP in the run, in index order, then variant order."""
    found = []
    for order, variant in enumerate(variants):
        prefix = f"{variant.key}-p"
        for pcap in (run_dir / "captures").glob(f"{prefix}*.pcap"):
            suffix = pcap.stem[len(prefix):]
            if suffix.isdigit():
                found.append((pcap.stem, int(suffix), variant.key, order))
    return [c[:3] for c in sorted(found, key=lambda c: (c[1], c[3]))]


def find_capture(run_dir: Path, variants: list[Variant], stem: str) -> tuple[int, Variant] | None:
    """The index and variant of the capture with this stem, if the run has it."""
    for variant in variants:
        prefix = f"{variant.key}-p"
        suffix = stem[len(prefix):]
        if stem.startswith(prefix) and suffix.isdigit() and (run_dir / "captures" / f"{stem}.pcap").is_file():
            return int(suffix), variant
    return None


# =============================================================================
# Run-level aggregates
# =============================================================================

_aggregate_cache: dict[str, tuple[tuple, dict]] = {}
_aggregate_lock = threading.Lock()


def forget(run_id: str) -> None:
    """Drop a deleted run's cached aggregate."""
    with _aggregate_lock:
        _aggregate_cache.pop(run_id, None)


def _weighted_median(counts: Counter) -> float | None:
    total = sum(counts.values())
    if not total:
        return None
    seen = 0
    for value in sorted(counts):
        seen += counts[value]
        if seen * 2 >= total:
            return value
    return None


def _summarize(records: list[dict]) -> dict:
    def values(key: str) -> list[float]:
        return [r["metrics"][key] for r in records if r["metrics"].get(key) is not None]

    sizes = Counter()
    for r in records:
        sizes.update({int(k): v for k, v in r["size_counts"].items()})
    return {
        "captures": len(records),
        "median_ttft_ms": _median(values("ttft_ms")),
        "median_events_per_s": _median(values("events_per_s")),
        "median_duration_s": _median(values("duration_s")),
        "median_gap_ms": _median(values("median_gap_ms")),
        "median_stream_packets": _median(values("stream_packets")),
        "median_packet_bytes": _weighted_median(sizes),
        "median_response_chars": _median(values("response_chars")),
        "total_bytes": sum(values("bytes")),
    }


def _by_category(records: list[dict], summarize=_summarize) -> list[dict]:
    # Library order (built-in categories first), then categories no longer in the library
    present = list(dict.fromkeys(r["category"] for r in records))
    order = [c["name"] for c in prompt_library.categories() if c["name"] in present]
    return [
        {"category": name, **summarize([r for r in records if r["category"] == name])}
        for name in order + [c for c in present if c not in order]
    ]


def _distributions(records: list[dict]) -> tuple[Counter, list[int]]:
    """Packet size counts and gap histogram over the records."""
    sizes = Counter()
    gap_hist = [0] * (len(GAP_EDGES_MS) - 1)
    for r in records:
        sizes.update({int(k): v for k, v in r["size_counts"].items()})
        gap_hist = [a + b for a, b in zip(gap_hist, r["gap_hist"])]
    return sizes, gap_hist


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def run_aggregate(run_id: str, run_dir: Path, variants: list[Variant], build=None, summarize=_summarize) -> dict:
    """The run's records and summaries: over all its captures, and per variant (`groups`).
    `build` and `summarize` replace build_record and the summary of a group of records."""
    captures = _captures(run_dir, variants)
    pcaps = [run_dir / "captures" / f"{stem}.pcap" for stem, _, _ in captures]
    # A capture's result can be saved after its last packet, so it counts as a change too
    results = [run_dir / "results" / f"{stem}.json" for stem, _, _ in captures]
    key = (len(pcaps), max((p.stat().st_mtime_ns for p in pcaps), default=0), max(map(_mtime_ns, results), default=0))
    with _aggregate_lock:
        cached = _aggregate_cache.get(run_id)
        if cached and cached[0] == key:
            return cached[1]

    records = []
    for stem, index, variant in captures:
        record = capture_record(run_dir, stem, index, build)
        records.append({**record, "key": stem, "variant": variant})
    sizes, gap_hist = _distributions(records)

    groups = []
    for variant in variants:
        mine = [r for r in records if r["variant"] == variant.key]
        group_sizes, group_gaps = _distributions(mine)
        groups.append({
            "key": variant.key,
            "label": variant.label,
            "summary": summarize(mine),
            "by_category": _by_category(mine, summarize),
            "size_counts": group_sizes,
            "gap_hist": group_gaps,
        })

    aggregate = {
        "summary": summarize(records),
        "by_category": _by_category(records, summarize),
        "groups": groups,
        "size_counts": sizes,
        "gap_hist": gap_hist,
        "records": records,
    }
    with _aggregate_lock:
        _aggregate_cache[run_id] = (key, aggregate)
    return aggregate


def _nice_step(span: float, max_bins: int) -> int:
    raw = max(span / max_bins, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * magnitude >= raw:
            return int(m * magnitude)
    return int(10 * magnitude)


def _quantile(counts: Counter, q: float) -> int:
    total = sum(counts.values())
    seen = 0
    for value in sorted(counts):
        seen += counts[value]
        if seen >= q * total:
            return value
    return max(counts)


def size_histogram(series: dict[str, Counter], max_bins: int = 48) -> dict:
    """Shared linear bins over the central 99% of all series' packet sizes."""
    merged = Counter()
    for counts in series.values():
        merged.update(counts)
    if not merged:
        return {"edges": [], "series": {k: [] for k in series}, "outside": {k: 0 for k in series}}
    lo, hi = _quantile(merged, 0.005), _quantile(merged, 0.995)
    step = _nice_step(hi - lo + 1, max_bins)
    start = (lo // step) * step
    n_bins = (hi - start) // step + 1
    edges = [start + i * step for i in range(n_bins + 1)]
    out_series, outside = {}, {}
    for key, counts in series.items():
        bins = [0] * n_bins
        skipped = 0
        for size, n in counts.items():
            i = (size - start) // step
            if 0 <= i < n_bins:
                bins[i] += n
            else:
                skipped += n
        out_series[key] = bins
        outside[key] = skipped
    return {"edges": edges, "series": out_series, "outside": outside}


def gap_histogram(series: dict[str, list[int]]) -> dict:
    """The log-scale gap bins, trimmed to the range any series uses."""
    used = [i for i in range(len(GAP_EDGES_MS) - 1) if any(c[i] for c in series.values())]
    if not used:
        return {"edges": [], "series": {k: [] for k in series}}
    lo, hi = used[0], used[-1] + 1
    return {
        "edges": GAP_EDGES_MS[lo:hi + 1],
        "series": {k: c[lo:hi] for k, c in series.items()},
    }


def capture_detail(run_dir: Path, stem: str, index: int, variant: Variant, max_points: int = 4000) -> dict:
    record = capture_record(run_dir, stem, index)
    packets = read_packets(run_dir / "captures" / f"{stem}.pcap")
    stream = _stream(packets)
    t0 = stream[0][0] if stream else 0
    step = max(1, math.ceil(len(stream) / max_points))
    timeline = [[round(p[0] - t0, 6), p[3]] for p in stream[::step]]

    result_file = run_dir / "results" / f"{stem}.json"
    result = json.loads(result_file.read_text()) if result_file.exists() else {}
    timing = result.get("timing") or []
    tstep = max(1, math.ceil(len(timing) / max_points))
    events = [[round(e["t"], 6), round(e["dt"] * 1000, 3), e["text"]] for e in timing[::tstep]]

    prompt_file = run_dir / "logs" / f"prompt_{index:02d}.txt"
    known = _known_prompt(run_dir, record["prompt"])
    prompt_text = prompt_file.read_text() if prompt_file.exists() else (known["text"] if known else "")
    return {
        "key": stem,
        "variant": variant.key,
        "index": index,
        "prompt": record["prompt"],
        "iteration": record["iteration"],
        "category": record["category"],
        "worker": record.get("worker"),
        "gpus": record.get("gpus"),
        "metrics": record["metrics"],
        "prompt_text": prompt_text.strip(),
        "response": result.get("response"),
        "stream_timeline": timeline,
        "events": events,
        "downsampled": step > 1 or tstep > 1,
    }
