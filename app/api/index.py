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
from experiments import engine as experiments
from experiments.routes import routers as experiment_routers
from prompt_library.routes import router as prompts_router
from settings.routes import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Remove Docker resources left by a run that died with a previous server.
    await run_in_threadpool(experiments.remove_orphaned_resources)
    await run_in_threadpool(experiments.mark_interrupted_runs)
    await run_in_threadpool(experiments.number_unnumbered_runs)
    yield
    # Stop active runs so they still remove their containers and images.
    await run_in_threadpool(experiments.shutdown)


app = FastAPI(
    title="RogueAgent Web API",
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
for router in experiment_routers:
    api.include_router(router)
app.include_router(api)
