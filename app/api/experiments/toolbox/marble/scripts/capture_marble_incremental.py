#!/usr/bin/env python3
"""Gradually builds the graph+star dataset in the order the task_id is
outermost: for task_id 1, run every (category x topology x repetition)
combo, then move to task_id 2, etc. Every single run is saved immediately
(pcap sliced + row appended to dataset_index.csv) rather than deferred to
the end of a batch, so the dataset is usable at any point and safe to
interrupt -- restarting this script skips any (category, task_id, topology,
repetition_id) combo already recorded with a real capture.

Usage:
    python3 scripts/capture_marble_incremental.py \\
        --out-root captures_marble_incremental \\
        --seed-from captures_marble_graph_v2/dataset_index.csv
"""

from __future__ import annotations

import argparse
import csv
import functools
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scapy.all import PcapReader, wrpcap  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_marble_dataset import run_task  # noqa: E402  (reuse the well-tested per-task runner)

print = functools.partial(print, flush=True)

ROOT = Path(__file__).resolve().parent.parent
MARBLE_DIR = ROOT / "marble"

CATEGORIES = ("bargaining", "research", "coding", "database", "bugfix",
              "swe_bench", "deep_research", "medical_diagnosis", "legal_review", "debate")
TOPOLOGIES = ("graph", "star")
NUM_TASKS = 15
NUM_REPS = 3  # repetition_id 0, 1, 2
MODEL_NAME = "llama3.2:3b"

FIELDNAMES = ["category", "task_id", "repetition_id", "model", "topology", "llm_pcap", "llm_packets", "agent_calls_json"]


def load_done(index_path: Path) -> set[tuple[str, int, str, int]]:
    done = set()
    if index_path.exists():
        with index_path.open() as f:
            for row in csv.DictReader(f):
                if int(row["llm_packets"]) > 0:
                    done.add((row["category"], int(row["task_id"]), row["topology"], int(row["repetition_id"])))
    return done


def seed_from_existing(index_path: Path, llm_dir: Path, existing_csv: Path) -> None:
    """Import already-collected rows from a prior non-incremental run (e.g.
    captures_marble_graph_v2) so that work doesn't get redone."""
    if not existing_csv.exists():
        print(f"--seed-from {existing_csv} does not exist, skipping seed")
        return
    rows = list(csv.DictReader(open(existing_csv)))
    imported = 0
    with index_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        for r in rows:
            if int(r["llm_packets"]) <= 0:
                continue
            src_pcap = Path(r["llm_pcap"])
            if src_pcap.exists():
                dst_pcap = llm_dir / src_pcap.name
                if not dst_pcap.exists():
                    shutil.copy2(src_pcap, dst_pcap)
                r["llm_pcap"] = str(dst_pcap)
            src_calls = Path(r.get("agent_calls_json", "") or "")
            if src_calls.exists():
                dst_calls = llm_dir / src_calls.name
                if not dst_calls.exists():
                    shutil.copy2(src_calls, dst_calls)
                r["agent_calls_json"] = str(dst_calls)
            writer.writerow({k: r.get(k, "") for k in FIELDNAMES})
            imported += 1
    print(f"seeded {imported} already-done rows from {existing_csv}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", default=str(ROOT / "captures_marble_incremental"))
    parser.add_argument("--seed-from", default=None,
                         help="existing dataset_index.csv to import as already-done, e.g. captures_marble_graph_v2/dataset_index.csv")
    parser.add_argument("--proxy-port", type=int, default=11443)
    parser.add_argument("--iface", default=("lo0" if sys.platform == "darwin" else "lo"))
    parser.add_argument("--categories", nargs="*", default=list(CATEGORIES), help="restrict to a subset (default: all 4)")
    parser.add_argument("--task-ids", type=int, nargs="*", default=list(range(1, NUM_TASKS + 1)), help="restrict to a subset (default: 1-15)")
    parser.add_argument("--topologies", nargs="*", default=list(TOPOLOGIES), help="restrict to a subset (default: graph star)")
    parser.add_argument("--reps", type=int, default=NUM_REPS, help="how many repetitions to add in this run (default: 3)")
    parser.add_argument("--rep-offset", type=int, default=0,
                         help="repetition_id to start this batch at (default: 0). Run again "
                              "with e.g. --rep-offset 3 to add a fresh batch of --reps more "
                              "repetitions on top of what's already collected, instead of "
                              "overlapping with repetition_ids already done.")
    args = parser.parse_args()

    # Must be absolute -- see capture_marble_dataset.py's out_root comment
    # for why (MARBLE_AGENT_CALL_LOG resolves against the subprocess's cwd,
    # not this script's).
    out_root = Path(args.out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    llm_dir = out_root / "captures_llm"
    llm_dir.mkdir(exist_ok=True)
    agent_call_log_dir = out_root / "agent_calls_tmp"
    agent_call_log_dir.mkdir(exist_ok=True)
    index_path = out_root / "dataset_index.csv"
    raw_pcap = out_root / "continuous_raw.pcap"

    if not index_path.exists():
        with index_path.open("w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()
        if args.seed_from:
            seed_from_existing(index_path, llm_dir, Path(args.seed_from))

    done = load_done(index_path)
    rep_range = range(args.rep_offset, args.rep_offset + args.reps)
    total = len(args.task_ids) * len(args.categories) * len(args.topologies) * len(rep_range)
    print(f"targeting repetition_id {rep_range.start}..{rep_range.stop - 1} this run")
    print(f"{len(done)} combos already done overall -- {total} targeted this run, skipping any already done")

    python = sys.executable
    env = os.environ.copy()
    env["MARBLE_OLLAMA_PROXY_URL"] = f"https://127.0.0.1:{args.proxy_port}"
    (MARBLE_DIR / "logs").mkdir(exist_ok=True)
    (MARBLE_DIR / "result").mkdir(exist_ok=True)

    print(f"starting TLS proxy on :{args.proxy_port} and continuous tcpdump...")
    proxy = subprocess.Popen(
        [python, str(ROOT / "scripts" / "tls_ollama_proxy.py"), "--listen-port", str(args.proxy_port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)
    if proxy.poll() is not None:
        raise RuntimeError(
            f"TLS proxy exited immediately (code {proxy.returncode}) -- port {args.proxy_port} "
            f"is likely already in use by a leftover process from a previous run. "
            f"Check with: lsof -i :{args.proxy_port}"
        )
    tcpdump = subprocess.Popen(
        # -U: packet-buffered output (flush to disk after every packet, via
        # pcap_dump_flush()) instead of tcpdump's default stdio buffering --
        # essential here since this script reads the pcap file *during*
        # capture, unlike the batch script which only ever reads it after
        # tcpdump has been killed (which forces a final flush anyway).
        # Without -U, drain_new_packets() sees nothing for a task that
        # genuinely captured real traffic, because tcpdump hasn't written
        # it to disk yet -- confirmed via smoke test (105 real packets for
        # a task, 0 read incrementally, all 665 appeared only after the
        # whole process exited and forced tcpdump's buffer to flush).
        ["sudo", "-n", "tcpdump", "-U", "-i", args.iface, "-w", str(raw_pcap), f"tcp port {args.proxy_port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)

    # One persistent reader for the whole run: after each task, drain
    # whatever new packets tcpdump has written since last time and buffer
    # them in memory. Re-scanning the entire (ever-growing) pcap file from
    # disk for every task would get slower and slower over what's meant to
    # be a long-running, gradually-built dataset -- this keeps each task's
    # incremental cost proportional only to that task's own packets.
    all_packets: list = []
    reader_holder: dict = {"reader": None}

    def drain_new_packets() -> None:
        if reader_holder["reader"] is None:
            if not raw_pcap.exists():
                return
            try:
                reader_holder["reader"] = PcapReader(str(raw_pcap))
            except Exception:
                return  # global header not fully flushed yet, try again next call
        reader = reader_holder["reader"]
        while True:
            try:
                pkt = reader.read_packet()
            except EOFError:
                break
            all_packets.append(pkt)

    try:
        for task_id in args.task_ids:
            for category in args.categories:
                for topology in args.topologies:
                    for repetition_id in rep_range:
                        key = (category, task_id, topology, repetition_id)
                        if key in done:
                            continue
                        if tcpdump.poll() is not None:
                            print(f"ABORTING: tcpdump (pid {tcpdump.pid}) died unexpectedly "
                                  f"(exit code {tcpdump.returncode}).")
                            return
                        print(f"running {category}/{topology}/task_{task_id}/rep{repetition_id}...")
                        rec = run_task(category, topology, task_id, python, env, agent_call_log_dir)
                        status = "OK" if rec["ok"] else f"FAILED: {rec['info'][:150]}"
                        duration = rec["t_end"] - rec["t_start"]
                        print(f"  {status} ({duration:.1f}s)")
                        with (out_root / "progress.jsonl").open("a") as pf:
                            pf.write(json.dumps({
                                "category": category, "task_id": task_id, "topology": topology,
                                "repetition_id": repetition_id, "ok": rec["ok"],
                                "duration_s": round(duration, 1),
                                "info": rec["info"][:150] if not rec["ok"] else "",
                            }) + "\n")

                        time.sleep(1.5)  # let tcpdump flush this task's last packets to disk
                        drain_new_packets()

                        n_packets = 0
                        out_pcap_path = ""
                        calls_path = ""
                        if rec["ok"]:
                            raw_bucket = [p for p in all_packets if rec["t_start"] - 1.0 <= float(p.time) <= rec["t_end"] + 1.0]
                            # Dedupe byte-identical packets -- if an orphaned
                            # tcpdump process from a prior interrupted run is
                            # still alive (we don't have passwordless sudo
                            # kill, so this happens), it independently
                            # captures the same real traffic into the same
                            # shared file, producing exact duplicate records.
                            # Confirmed via md5: duplicates are byte-for-byte
                            # identical, so keeping first-occurrence-only is
                            # safe and recovers the correct single-capture
                            # stream, not data loss.
                            seen_hashes = set()
                            bucket = []
                            for p in raw_bucket:
                                h = hashlib.md5(bytes(p)).hexdigest()
                                if h not in seen_hashes:
                                    seen_hashes.add(h)
                                    bucket.append(p)
                            base_name = f"{category}_{topology}_ollama-llama3.2-3b_{task_id:03d}_rep{repetition_id}"
                            if bucket:
                                out_pcap_path = str(llm_dir / f"{base_name}.pcap")
                                wrpcap(out_pcap_path, bucket)
                                n_packets = len(bucket)
                            else:
                                print("  WARNING: successful task but 0 packets captured -- capture may have stalled")
                            calls_path = str(llm_dir / f"{base_name}.agent_calls.json")
                            Path(calls_path).write_text(json.dumps(rec["agent_calls"]))

                        # Save immediately -- this is the whole point: the
                        # dataset is usable after every single run, not just
                        # at the end of a multi-hour batch.
                        with index_path.open("a", newline="") as f:
                            csv.DictWriter(f, fieldnames=FIELDNAMES).writerow({
                                "category": category, "task_id": task_id, "repetition_id": repetition_id,
                                "model": MODEL_NAME, "topology": topology,
                                "llm_pcap": out_pcap_path, "llm_packets": n_packets,
                                "agent_calls_json": calls_path,
                            })
                        if rec["ok"] and n_packets > 0:
                            done.add(key)
                            print(f"  saved ({len(done)}/{total} total done)")
    finally:
        if reader_holder["reader"] is not None:
            reader_holder["reader"].close()
        proxy.terminate()
        subprocess.run(["sudo", "-n", "kill", str(tcpdump.pid)], capture_output=True)
        time.sleep(1.0)
        print(f"tcpdump pid (clean up manually if still running): {tcpdump.pid}")

    print(f"\nall combos processed: {len(done)}/{total} done")


if __name__ == "__main__":
    main()
