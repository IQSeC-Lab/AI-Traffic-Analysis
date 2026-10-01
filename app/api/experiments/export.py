"""Downloads of a run's results: every file as a zip, and the per-capture metrics as CSV."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Iterator

from .base import Variant

RUN_FILES = ("run.json", "run.log", "prompts.json")
RUN_FOLDERS = ("captures", "results", "logs")   # the analysis/ cache is left out; it is rebuilt from these

METRIC_COLUMNS = [
    "events", "ttft_ms", "duration_s", "events_per_s", "response_chars",
    "stream_packets", "stream_bytes", "stream_s", "median_packet_bytes", "median_gap_ms",
    "packets", "bytes", "capture_s",
]


class _Buffer(io.RawIOBase):
    """Write-only stream the zip is written into; the generator hands out what arrived."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:
        self._chunks.append(bytes(b))
        return len(b)

    def drain(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


def zip_run(run_dir: Path, name: str) -> Iterator[bytes]:
    """Stream a zip of the run's files, so large runs never sit in memory or a temp file."""
    files = [run_dir / f for f in RUN_FILES if (run_dir / f).is_file()]
    for folder in RUN_FOLDERS:
        if (run_dir / folder).is_dir():
            files += sorted(p for p in (run_dir / folder).iterdir() if p.is_file())

    buffer = _Buffer()
    # PCAPs barely compress, so the fastest level keeps downloads quick.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for path in files:
            with path.open("rb") as src, archive.open(f"{name}/{path.relative_to(run_dir)}", "w", force_zip64=True) as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
                    if data := buffer.drain():
                        yield data
        if data := buffer.drain():
            yield data
    yield buffer.drain()   # the zip's central directory


def captures_csv(records: list[dict], variants: list[Variant]) -> str:
    """One row per capture: its file stem, the settings of its variant (temperature, model,
    network condition), its prompt, the worker that made it and its metrics."""
    by_key = {v.key: v for v in variants}
    settings = list(dict.fromkeys(c for v in variants for c in v.columns))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["capture", *settings, "index", "prompt", "iteration", "category", "worker", "gpus", *METRIC_COLUMNS])
    for r in records:
        m = r.get("metrics") or {}
        gpus = r.get("gpus")
        columns = by_key[r["variant"]].columns
        writer.writerow([
            r["key"], *(columns.get(c) for c in settings),
            r["index"], r["prompt"], r["iteration"], r["category"], r.get("worker"),
            " ".join(map(str, gpus)) if gpus is not None else None,
            *(m.get(c) for c in METRIC_COLUMNS),
        ])
    return out.getvalue()
