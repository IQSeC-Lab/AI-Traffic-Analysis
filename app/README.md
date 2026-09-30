# app

Web app for running the MaLLM experiments. Next.js (TypeScript, App Router) frontend with a FastAPI backend in `api/`.

```
app/                              # project root
├── api/                          # FastAPI backend, all routes under /api
│   ├── index.py                  # app, routers, startup/shutdown hooks
│   ├── storage.py                # where models, outputs and settings live
│   ├── system.py                 # GPU (nvidia-smi) and Docker detection
│   ├── settings/                 # HF token + model downloader
│   ├── prompt_library/           # built-in prompts + your own (/api/prompts)
│   └── data_collector/           # experiment 2, ported from ../2-Data-Collector
│       ├── experiment.py         # runs, workers, queue + Docker cleanup
│       ├── scheduler.py          # which GPU a run's workers go to, and when
│       ├── analysis.py           # PCAP parsing and run analytics
│       ├── export.py             # zip and CSV downloads
│       └── toolbox/              # Docker build context (inference server + client)
├── app/                          # Next.js pages (see below)
├── components/                   # UI: shell/, charts/, experiments/, settings/, overview/
├── lib/                          # API client, formatting, theme, experiments list
└── next.config.ts                # proxies /api/* → FastAPI
```

Next.js requires its router folder to be named `app/`, which is why there is an `app/app/`. Requests to `/api/*` hit the rewrite in `next.config.ts` and are forwarded to FastAPI on port 8000.

## Setup

Run this on the machine that has Docker and the GPUs (NVIDIA driver + `nvidia-container-toolkit`).

```bash
npm install
npm run setup:api   # creates .venv and installs the Python dependencies
```

## Run

```bash
npm run dev         # Next.js on :3000 + FastAPI on :8000
```

Open http://localhost:3000. API docs: http://localhost:3000/api/docs.

`dev:api` restarts FastAPI whenever a file in `api/` changes, which cancels a running experiment. For long experiments run the API without reload in its own terminal: `npm run start:api` together with `npm run dev:next`.

## Using it

The sidebar lists the experiments. Only the Data Collector is available so far; the others are added one at a time.

| Page | What it's for |
| --- | --- |
| **Overview** (`/`) | Totals, the run in progress, host status (Docker, GPU memory), recent runs |
| **Data Collector › Runs** | Every run, newest first |
| **Data Collector › New run** | Pick a downloaded model, the hardware (Auto, chosen GPUs, or CPU), the number of workers, prompts, repeats and max tokens |
| **Run page** | *Monitor*: queue position, live progress, what each worker is doing, log, Cancel. *Results*: the run's analytics, and every capture with its packets on the wire, prompt, response and a PCAP download. *Export files* downloads the whole run as a zip, *Metrics CSV* one row per capture (with the worker and GPU that made it). Finished runs can be deleted here or from the runs list |
| **Prompts** | The prompt library: the 60 built-in prompts plus your own, in your own categories. Add prompts here or from *New run* |
| **Settings** | Theme (light / dark / system) and accent color, the results folder, HuggingFace token, model downloads and deletion |

Every run gets a number (#1, #2, …) shown as a colored badge; numbers are never reused, so #7 always means the same run. A run can also have a name, set when starting it or later from its page.

Runs are saved in the results folder (`data/` by default, changeable in Settings), so the history survives restarts; a run that was active when the API stopped shows as *interrupted*.

### Workers, parallel runs and the queue

- **Workers.** A run can have several workers. Each is its own model instance with its own containers, its own isolated Docker network and its own packet capture. The prompts are divided evenly and fixed when the run starts: worker 1 takes the 1st, 3rd, 5th… capture and worker 2 the 2nd, 4th, 6th…, so 6 prompts on 2 workers is 3 each, and no prompt category ends up on only one GPU. Every capture is still one prompt in a fresh container.
- **Choose GPUs** (the default when the host has several). *One copy per GPU*: every selected GPU runs its own worker (or several, with *Workers per GPU*), so 2 GPUs run 2 copies of the model side by side. *Split one copy across them*: every worker's model is spread over all the selected GPUs, for models too large for one GPU.
- **Auto** spreads the workers over the GPUs with free memory: the GPU with the fewest of the run's workers first, then the one with the most room.
- **Parallel runs.** Several runs can be active at once. Each has its own container names and networks.
- **GPU memory.** A model needs roughly its weight files +15% plus 1.5 GB (shown in Settings → Models). Each worker reserves that on its GPU for the whole run.
- **Queue.** A run that doesn't fit yet waits in the queue with the reason shown, and starts by itself as soon as there is room. CPU runs go one at a time.
- Workers or runs that share a GPU or the CPU slow each other down, which changes the timings being captured.

### Analytics

Each capture is parsed from its PCAP (no Wireshark needed) plus the client's per-event timing. The **stream** is the server → client TCP connection that carried the response; the client's `/health` polls are excluded.

| Metric | Meaning |
| --- | --- |
| First event | Time from the response starting to the first SSE event, at the client |
| Events/s | SSE events per second over the response (an event is one text chunk from the streamer, often a word) |
| Packet gap | Time between consecutive stream packets on the wire |
| Packet size | TCP payload of each stream packet |
| Packets | Stream packets carrying data |

Results are cached per capture in `analysis/` next to the PCAPs and rebuilt if a PCAP changes.

## Docker cleanup

Everything a Data Collector run creates is labeled `mallm.data-collector.run=<run id>`. When the run ends (completed, failed or cancelled), it removes:

- its containers (inference servers, tcpdump sidecars, clients)
- its Docker networks: `mallm-<run id>`, or `mallm-<run id>-w1`, `-w2`, … with several workers
- the `mallm-llm-toolbox:<run id>` image it built
- images the app had to pull (the base image, `nicolaka/netshoot`). These are shared by concurrent runs, so the last run to finish removes them

Nothing without that label is touched. If the API process dies mid-run, the next start of the API removes the leftovers. Docker's build cache is kept, so the next build takes seconds instead of reinstalling torch.

## Outputs

| Path                                   | Contents                                               |
| -------------------------------------- | ------------------------------------------------------ |
| `data/data-collector/<run id>/captures` | PCAP per prompt, as in `2-Data-Collector`              |
| `data/data-collector/<run id>/results`  | client output per capture: response + per-event timing, and the worker and GPUs that ran it |
| `data/data-collector/<run id>/logs`     | prompt text, model response and server logs            |
| `data/data-collector/<run id>/analysis` | cached analytics per capture                           |
| `data/data-collector/<run id>/run.json` | the run's settings, status and cleanup report          |
| `data/data-collector/<run id>/run.log`  | the run's full log                                     |
| `data/prompts.json`                    | your prompts (numbered from 61; numbers are never reused) |
| `data/settings.json`                   | saved settings, including the HF token (owner-only)    |
| `models/<org>-<name>`                  | downloaded models                                      |

## Configuration

| Variable           | Default                 | Description                                                    |
| ------------------ | ----------------------- | -------------------------------------------------------------- |
| `MALLM_MODELS_DIR` | `models/`               | Downloaded models. Point it at an existing models folder to reuse it. |
| `MALLM_DATA_DIR`   | `data/`                 | Settings, prompts, and experiment outputs unless another results folder is set in Settings. |
| `HF_TOKEN`         | none                    | HuggingFace token, used when none is saved in Settings.        |
| `API_PORT` | `8000` | Port of the FastAPI backend. Used by the `dev:api`/`start:api` scripts *and* by Next.js to forward `/api/*`, so set it for both (e.g. `API_PORT=8007 npm run dev`). |
| `API_URL` | `http://127.0.0.1:$API_PORT` | Full address Next.js forwards `/api/*` to, if the backend is on another host. Read at build time for `next build`. |
