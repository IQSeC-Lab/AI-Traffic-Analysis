"""
HTTP endpoints of the capture experiments: the same set under /api/<slug> for each
experiment (/api/data-collector, /api/temperature-change, ...), plus
/api/experiments for the runs of all of them.
"""

# No `from __future__ import annotations` here: make_router's endpoints annotate their
# body with the experiment's config class, which FastAPI must see as a class, not a string.

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import analysis, engine, export
from .base import NAME_MAX, Kind
from .kinds import KINDS


class RunUpdate(BaseModel):
    name: str | None = Field(None, max_length=NAME_MAX)


def _run_title(run) -> str:
    summary = run.summary()
    return summary.get("name") or ", ".join(summary.get("models") or [summary["config"].get("model", run.id)])


def _analytics(groups: list[tuple[str, str, dict]]) -> dict:
    """Summaries and distributions of (key, label, aggregate) groups, on shared bins."""
    return {
        "groups": [
            {"key": key, "label": label, "summary": a["summary"], "by_category": a["by_category"]}
            for key, label, a in groups
        ],
        "gap_hist": analysis.gap_histogram({key: a["gap_hist"] for key, _, a in groups}),
        "size_hist": analysis.size_histogram({key: a["size_counts"] for key, _, a in groups}),
    }


def make_router(kind: Kind) -> APIRouter:
    router = APIRouter(prefix=f"/{kind.slug}", tags=[kind.title])
    Config = kind.config

    def _get_run(run_id: str):
        run = engine.get(kind, run_id)
        if run is None:
            raise HTTPException(404, f"Run not found: {run_id}")
        return run

    def _aggregate(run) -> dict:
        return analysis.run_aggregate(run.id, run.run_dir, run.variants)

    def _capture(run, key: str):
        found = analysis.find_capture(run.run_dir, run.variants, key)
        if found is None:
            raise HTTPException(404, f"Capture {key} not found in run {run.id}")
        return found

    @router.post("/runs", status_code=202)
    def start_run(config: Config) -> dict:
        """Start a run in the background: right away if its GPU has room, otherwise it is queued."""
        try:
            run = engine.submit(kind, config)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return run.summary()

    @router.get("/runs")
    def list_runs() -> list[dict]:
        return [run.summary() for run in engine.all_runs(kind)]

    @router.get("/active")
    def active_runs() -> list[dict]:
        """Running and queued runs, oldest first."""
        return [run.summary() for run in engine.active_runs(kind)]

    @router.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        return _get_run(run_id).summary()

    @router.patch("/runs/{run_id}")
    def rename_run(run_id: str, body: RunUpdate) -> dict:
        """Set or clear the run's name."""
        run = _get_run(run_id)
        run.rename((body.name or "").strip() or None)
        return run.summary()

    @router.delete("/runs/{run_id}", status_code=204)
    def delete_run(run_id: str) -> Response:
        """Permanently delete a finished run and its files. Active runs must be cancelled first."""
        try:
            deleted = engine.delete(kind, run_id)
        except engine.RunConflict as e:
            raise HTTPException(409, str(e))
        if not deleted:
            raise HTTPException(404, f"Run not found: {run_id}")
        analysis.forget(run_id)
        return Response(status_code=204)

    @router.get("/runs/{run_id}/logs")
    def get_run_logs(run_id: str, after: int = Query(0, ge=0)) -> dict:
        """Log lines after sequence number `after`. Pass back `next` to keep tailing."""
        return _get_run(run_id).logs_after(after)

    @router.post("/runs/{run_id}/cancel", status_code=202)
    def cancel_run(run_id: str) -> dict:
        """Stop the run. Its containers, network and images are still removed."""
        run = _get_run(run_id)
        run.cancel()
        return run.summary()

    # ── Analytics ────────────────────────────────────────────────────────────

    @router.get("/analytics")
    def compare_runs(runs: str = Query(..., description="Comma-separated run ids")) -> dict:
        """Summaries and distributions of one or more runs (all their captures each), on shared bins."""
        ids = [r for r in dict.fromkeys(runs.split(",")) if r][:8]
        return _analytics([(r.id, _run_title(r), _aggregate(r)) for r in map(_get_run, ids)])

    @router.get("/runs/{run_id}/analytics")
    def run_analytics(run_id: str) -> dict:
        """The run's summary, and its summaries and distributions per variant (temperature,
        model, network condition; a single group for the Data Collector), on shared bins."""
        aggregate = _aggregate(_get_run(run_id))
        groups = [(g["key"], g["label"], g) for g in aggregate["groups"]]
        return {"summary": aggregate["summary"], **_analytics(groups)}

    @router.get("/runs/{run_id}/captures")
    def list_captures(run_id: str) -> list[dict]:
        records = _aggregate(_get_run(run_id))["records"]
        fields = ("key", "variant", "index", "prompt", "iteration", "category", "worker", "gpus", "metrics", "error")
        return [{k: r.get(k) for k in fields} for r in records]

    @router.get("/runs/{run_id}/export.zip")
    def export_run(run_id: str) -> StreamingResponse:
        """Every file of the run (PCAPs, client results, logs, run.json) as one zip."""
        run = _get_run(run_id)
        return StreamingResponse(
            export.zip_run(run.run_dir, run.id),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="mallm-{run.id}.zip"'},
        )

    @router.get("/runs/{run_id}/captures.csv")
    def export_metrics(run_id: str) -> Response:
        """One row per capture with its settings and metrics, for spreadsheets or pandas."""
        run = _get_run(run_id)
        return Response(
            export.captures_csv(_aggregate(run)["records"], run.variants),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="mallm-{run.id}-captures.csv"'},
        )

    @router.get("/runs/{run_id}/captures/{key}")
    def get_capture(run_id: str, key: str) -> dict:
        """A capture by its key (file stem, e.g. Qwen-Qwen2.5-7B-Instruct-p01)."""
        run = _get_run(run_id)
        index, variant = _capture(run, key)
        return analysis.capture_detail(run.run_dir, key, index, variant)

    @router.get("/runs/{run_id}/captures/{key}/pcap")
    def download_pcap(run_id: str, key: str) -> FileResponse:
        run = _get_run(run_id)
        _capture(run, key)
        return FileResponse(
            run.run_dir / "captures" / f"{key}.pcap",
            media_type="application/vnd.tcpdump.pcap",
            filename=f"{run.id}-{key}.pcap",
        )

    return router


# ── Every experiment ─────────────────────────────────────────────────────────

all_router = APIRouter(prefix="/experiments", tags=["experiments"])


@all_router.get("/runs")
def list_all_runs() -> list[dict]:
    """Runs of every experiment, newest first. Each has its experiment's slug in `experiment`."""
    return [run.summary() for run in engine.all_runs()]


@all_router.get("/active")
def all_active_runs() -> list[dict]:
    """Running and queued runs of every experiment, oldest first."""
    return [run.summary() for run in engine.active_runs()]


routers = [all_router, *(make_router(kind) for kind in KINDS.values())]
