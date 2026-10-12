"""
The capture of Agent to Infrastructure (agent_infrastructure.py). It is marble_engine.py's
capture with a database added: each worker still keeps its Ollama and TLS proxy for its
share of the run, and for each task (and repetition), once per topology:
  1. Start PostgreSQL in a fresh container on the worker's network. Its own start-up creates
     the store's tables and rows (store_db.py) before it listens, so none of that is traffic.
  2. Start the tcpdump sidecar on the database's network interface
  3. Run MARBLE in a fresh container, started through toolbox/marble_infra.py: the agents
     reach the database by its container name, every query its own TLS connection
  4. Save the PCAP and which agent ran each statement and when (<stem>.tool_calls.json),
     beside the agents' LLM calls (<stem>.agent_calls.json), then remove the database

The capture holds the agents' traffic with the database only. Their calls to the model go
to another container and are not in it; Agent to LLM captures those.
"""

from __future__ import annotations

import time

from . import agent_infrastructure as infra
from . import docker_cli as docker
from . import store_db
from .engine import TOOLBOX_DIR, FatalRunError
from .marble_engine import MarbleExperiment

POSTGRES_IMAGE = "postgres:16"
LAUNCHER = TOOLBOX_DIR / "marble_infra.py"
START_TIMEOUT = 90   # seconds for PostgreSQL to create the store and listen
# The image's own self-signed certificate (Debian's ssl-cert package), which its postgres user can read
TLS_ARGS = [
    "-c", "ssl=on",
    "-c", "ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem",
    "-c", "ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key",
]


class InfrastructureExperiment(MarbleExperiment):
    LAUNCHER = LAUNCHER

    def _images(self) -> list[str]:
        return [*super()._images(), POSTGRES_IMAGE]

    def _setup(self) -> None:
        super()._setup()
        if self._cancel.is_set():
            return
        self._set_step("Pulling the PostgreSQL image")
        docker.must("pull", POSTGRES_IMAGE, ctx=f"docker pull {POSTGRES_IMAGE}")
        # What every task's database starts from, kept with the run's configs. PostgreSQL reads
        # it as its own user, not as the one the API runs as.
        seed = self._seed_dir / "store.sql"
        self._seed_dir.mkdir(parents=True, exist_ok=True)
        seed.write_text(store_db.seed_sql())
        self._seed_dir.chmod(0o755)
        seed.chmod(0o644)
        self.log(f"[setup] ✓ The store's database: {seed}")

    @property
    def _seed_dir(self):
        return self.configs_dir / "database"

    def _db(self, k: int) -> str:
        return f"mallm-{self.id}-w{k + 1}-db"

    def _task_config(self, task: dict, topology: str) -> str:
        return infra.task_config(task, topology, self.config.model)

    def _capture_container(self, k: int, llm: str, stem: str) -> str:
        """A new database for the task, listening once the store is in it."""
        db = self._db(k)
        docker.rm_container(db)
        self._set_step("Starting the database")
        docker.must(
            "run", "-d", "--name", db, "--label", self.label,
            "--hostname", db,
            "--network", self._workers[k]["network"],
            "-e", f"POSTGRES_USER={store_db.USER}",
            "-e", f"POSTGRES_PASSWORD={store_db.PASSWORD}",
            "-e", f"POSTGRES_DB={store_db.DATABASE}",
            # In the container's own layer, so it goes with the container (the image's default is a volume)
            "-e", "PGDATA=/pgdata",
            "-v", f"{self._seed_dir}:/docker-entrypoint-initdb.d:ro",
            POSTGRES_IMAGE, *TLS_ARGS,
            ctx="start PostgreSQL",
        )
        # While it creates the store PostgreSQL only listens on a socket; over TCP it is ready
        deadline = time.monotonic() + START_TIMEOUT
        ready = ["exec", db, "pg_isready", "-q", "-h", "127.0.0.1", "-U", store_db.USER, "-d", store_db.DATABASE]
        while docker.run(*ready).returncode != 0:
            if self._cancel.is_set():
                return db
            if time.monotonic() > deadline or not self._is_running(db):
                logs = docker.run("logs", "--tail", "20", db)
                raise FatalRunError(f"PostgreSQL did not start: {(logs.stderr or logs.stdout).strip()[-800:]}")
            time.sleep(0.5)
        self.log(f"[database] ✓ Store created: {db}:{store_db.PORT}")
        return db

    def _agents_args(self, k: int, stem: str) -> list[str]:
        (self.results_dir / f"{stem}.tools.jsonl").unlink(missing_ok=True)
        return [
            "-e", f"MARBLE_DB_HOST={self._db(k)}",
            "-e", f"MARBLE_DB_PORT={store_db.PORT}",
            "-e", f"MARBLE_DB_NAME={store_db.DATABASE}",
            "-e", f"MARBLE_DB_USER={store_db.USER}",
            "-e", f"MARBLE_DB_PASSWORD={store_db.PASSWORD}",
            "-e", f"MARBLE_TOOL_CALL_LOG=/out/{stem}.tools.jsonl",
        ]

    def _task_record(self, k: int, stem: str) -> dict:
        """The statements the agents ran, saved beside the PCAP like their LLM calls."""
        queries = self._tool_calls(stem)
        failed = sum(q.get("status") == "error" for q in queries)
        helped = sum(q.get("origin", "call") != "call" for q in queries)
        self.log(f"[database] {len(queries)} statement{'' if len(queries) == 1 else 's'} run"
                 + (f", {failed} refused" if failed else "") + (f", {helped} read from an answer that was not a call" if helped else ""))
        return {"queries": len(queries), "queries_failed": failed, "queries_helped": helped}

    def _task_problem(self, record: dict) -> str | None:
        if not record.get("queries"):
            return "The agents sent no statement to the database, so the capture holds nothing."
        if record["queries"] == record.get("queries_failed"):
            return "The database refused every statement the agents sent."
        return None

    def _after_task(self, k: int) -> None:
        docker.rm_container(self._db(k))
