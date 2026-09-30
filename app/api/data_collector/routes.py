"""HTTP endpoints for the data collector, mounted at /api/data-collector."""

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import analysis, experiment, export
from .experiment import ExperimentConfig

router = APIRouter(prefix="/data-collector", tags=["data-collector"])


def _get_run(run_id: str):
    run = experiment.get(run_id)
    if run is None:
        raise HTTPException(404, f"Run not found: {run_id}")
    return run


def _capture_stem(run, index: int) -> str:
    stem = f"{run.model_safe}-p{index:02d}"
    if not (run.run_dir / "captures" / f"{stem}.pcap").exists():
        raise HTTPException(404, f"Capture {index} not found in run {run.id}")
    return stem


@router.post("/runs", status_code=202)
def start_run(config: ExperimentConfig) -> dict:
    """Start a run in the background: right away if its GPU has room, otherwise it is queued."""
    try:
        run = experiment.submit(config)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return run.summary()


@router.get("/runs")
def list_runs() -> list[dict]:
    return [run.summary() for run in experiment.all_runs()]


@router.get("/active")
def active_runs() -> list[dict]:
    """Running and queued runs, oldest first."""
    return [run.summary() for run in experiment.active_runs()]


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _get_run(run_id).summary()


class RunUpdate(BaseModel):
    name: str | None = Field(None, max_length=experiment.NAME_MAX)


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
        deleted = experiment.delete(run_id)
    except experiment.RunConflict as e:
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


# ── Analytics ────────────────────────────────────────────────────────────────


@router.get("/analytics")
def compare_runs(runs: str = Query(..., description="Comma-separated run ids")) -> dict:
    """Summaries and distributions for one or more runs, on shared bins."""
    ids = [r for r in dict.fromkeys(runs.split(",")) if r][:8]
    selected = [_get_run(r) for r in ids]
    aggregates = {r.id: analysis.run_aggregate(r.id, r.run_dir, r.model_safe) for r in selected}
    return {
        "runs": [
            {
                "id": r.id,
                "model": r.summary()["config"]["model"],
                "status": r.summary()["status"],
                "created_at": r.summary()["created_at"],
                "summary": aggregates[r.id]["summary"],
                "by_category": aggregates[r.id]["by_category"],
            }
            for r in selected
        ],
        "gap_hist": analysis.gap_histogram({k: a["gap_hist"] for k, a in aggregates.items()}),
        "size_hist": analysis.size_histogram({k: a["size_counts"] for k, a in aggregates.items()}),
    }


@router.get("/runs/{run_id}/captures")
def list_captures(run_id: str) -> list[dict]:
    run = _get_run(run_id)
    records = analysis.run_aggregate(run.id, run.run_dir, run.model_safe)["records"]
    return [
        {k: r.get(k) for k in ("index", "prompt", "iteration", "category", "worker", "gpus", "metrics", "error")}
        for r in records
    ]


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
    """One row per capture with its metrics, for spreadsheets or pandas."""
    run = _get_run(run_id)
    records = analysis.run_aggregate(run.id, run.run_dir, run.model_safe)["records"]
    return Response(
        export.captures_csv(records),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="mallm-{run.id}-captures.csv"'},
    )


@router.get("/runs/{run_id}/captures/{index}")
def get_capture(run_id: str, index: int) -> dict:
    run = _get_run(run_id)
    return analysis.capture_detail(run.run_dir, _capture_stem(run, index), index)


@router.get("/runs/{run_id}/captures/{index}/pcap")
def download_pcap(run_id: str, index: int) -> FileResponse:
    run = _get_run(run_id)
    stem = _capture_stem(run, index)
    return FileResponse(
        run.run_dir / "captures" / f"{stem}.pcap",
        media_type="application/vnd.tcpdump.pcap",
        filename=f"{run.id}-{stem}.pcap",
    )
