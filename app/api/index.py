"""
FastAPI backend for the web app.

Every route lives under /api so Next.js can proxy /api/* here
(see the rewrite in next.config.ts).

Run from the app/ folder:
    npm run dev:api
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.concurrency import run_in_threadpool

import system
from data_collector import experiment as data_collector
from data_collector.routes import router as data_collector_router
from prompt_library.routes import router as prompts_router
from settings.routes import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Remove Docker resources left by a run that died with a previous server.
    await run_in_threadpool(data_collector.remove_orphaned_resources)
    await run_in_threadpool(data_collector.mark_interrupted_runs)
    await run_in_threadpool(data_collector.number_unnumbered_runs)
    yield
    # Stop an active run so it still removes its containers and images.
    await run_in_threadpool(data_collector.shutdown)


app = FastAPI(
    title="MaLLM Web API",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


api.include_router(system.router)
api.include_router(settings_router)
api.include_router(prompts_router)
api.include_router(data_collector_router)
app.include_router(api)
