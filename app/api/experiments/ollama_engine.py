"""
The capture of engine.py with Ollama as the inference server, for experiments run with the
Ollama provider. Everything else is the engine's: a fresh server container per prompt, the
tcpdump sidecar sharing its network, a client on the isolated network, the same files.

  - The server is the ollama/ollama image with OLLAMA_DIR mounted, listening on the port the
    app's own server uses, so the analysis finds the response stream the same way.
  - The client (toolbox/client_ollama.py) loads the model, then streams /api/generate. It
    needs nothing but Python, so no image is built: it runs in the plain Python image.
  - The model is one downloaded in Settings (settings/ollama_models.py).
"""

from __future__ import annotations

from storage import OLLAMA_DIR

from . import docker_cli as docker
from . import engine
from .base import Variant
from .engine import DOCKERFILE, INFERENCE_PORT, NETSHOOT_IMAGE, TOOLBOX_DIR, Experiment

# Kept on the host after the run: it is several GB, and every run on Ollama needs it.
OLLAMA_IMAGE  = "ollama/ollama"
CLIENT_SCRIPT = TOOLBOX_DIR / "client_ollama.py"


def ensure_ollama_image(run: Experiment) -> None:
    if not docker.exists("image", OLLAMA_IMAGE):
        run.log(f"[setup] Pulling {OLLAMA_IMAGE} (kept for later runs)...")
        docker.must("pull", OLLAMA_IMAGE, ctx=f"docker pull {OLLAMA_IMAGE}")


class OllamaExperiment(Experiment):
    def _setup(self) -> None:
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self._client_image = docker.base_image(DOCKERFILE)   # the Python image the toolbox is built on
        with engine._lock:
            new = [img for img in (self._client_image, NETSHOOT_IMAGE) if not docker.exists("image", img)]
            engine._set_pulled_images(engine._pulled_images() + new)

        self._set_step("Pulling the Ollama, client and tcpdump images")
        ensure_ollama_image(self)
        docker.must("pull", self._client_image, ctx=f"docker pull {self._client_image}")
        docker.run("pull", NETSHOOT_IMAGE)
        self.log("[setup] ✓ Images ready.")

        self._set_step("Preparing network" + ("s" if len(self._workers) > 1 else ""))
        for w in self._workers:
            docker.must(
                "network", "create", "--driver", "bridge", "--internal",
                "--label", self.label, w["network"],
                ctx=f"create network {w['network']}",
            )
            self.log(f"[setup] ✓ Created isolated network: {w['network']}")

    def _start_inference(self, k: int, variant: Variant) -> str:
        cname = f"mallm-{self.id}-w{k + 1}-llm"
        docker.rm_container(cname)
        docker.must(
            "run", "-d", "--name", cname, "--label", self.label,
            "--network", self._workers[k]["network"],
            *engine._gpu_args(self._workers[k]["gpus"]),
            "-v", f"{OLLAMA_DIR}:/root/.ollama",
            "-e", f"OLLAMA_HOST=0.0.0.0:{INFERENCE_PORT}",
            OLLAMA_IMAGE,
            ctx="start Ollama",
        )
        self.log(f"[inference] ✓ Container started: {cname} (Ollama)")
        return cname

    def _client_command(self, variant: Variant) -> list[str]:
        sampling = [] if variant.temperature is None else ["--temperature", str(variant.temperature)]
        return [
            "-v", f"{CLIENT_SCRIPT}:/client_ollama.py:ro",
            self._client_image, "python", "/client_ollama.py",
            "--model", variant.model,
            *sampling,
        ]
