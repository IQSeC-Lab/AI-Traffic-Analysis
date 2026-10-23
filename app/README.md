# app

Web app for running the MaLLM experiments. Next.js (TypeScript, App Router) frontend with a FastAPI backend in `api/`.

```
app/                              # project root
├── api/                          # FastAPI backend, all routes under /api
│   ├── index.py                  # app, routers, startup/shutdown hooks
│   ├── storage.py                # where models, outputs and settings live
│   ├── console.py                # server console output that survives a dropped terminal
│   ├── system.py                 # GPU (nvidia-smi) and Docker detection
│   ├── settings/                 # HF token + model downloader
│   ├── prompt_library/           # built-in prompts + your own (/api/prompts)
│   └── experiments/              # the capture experiments, one engine for all of them
│       ├── data_collector.py     # 2, ported from ../2-Data-Collector
│       ├── custom_prompts.py     # 4, ported from ../4-Crafted-Prompts, with its own prompts
│       ├── temperature_change.py # 3, ported from ../3-Temperature-change
│       ├── scalability.py        # 5, ported from ../5-Scalability
│       ├── delay.py              # 6, ported from ../6-Delay
│       ├── custom_experiment.py  # not in the repo: scenarios with every setting of the others
│       ├── ollama_engine.py      # the same capture with Ollama as the server (the Ollama provider)
│       ├── topology_transfer.py  # agentic, Agent to LLM: MARBLE tasks, once per coordination topology
│       ├── marble_engine.py      # how an agentic run captures a task
│       ├── agent_infrastructure.py  # agentic, Agent to Infrastructure: requests on a database
│       ├── store_db.py           # its mock database (an online store) and the requests
│       ├── infra_engine.py       # marble_engine.py's capture with a database per task
│       ├── agent_endpoint.py     # agentic, Agent to Endpoint: lookups on public sites
│       ├── endpoint_engine.py    # marble_engine.py's capture on the agents' side, with internet
│       ├── marble_common.py      # what the two experiments with tasks of their own share
│       ├── marble_analysis.py    # analytics of the agentic runs (the dataset's measurements, the heatmap)
│       ├── marble_classifier.py  # task fingerprinting on an agentic run (Random Forest: transfer, visibility, importance)
│       ├── engine.py             # runs, workers, the shared queue + Docker cleanup
│       ├── scheduler.py          # which GPU a run's workers go to, and when
│       ├── analysis.py           # PCAP parsing and run analytics
│       ├── export.py             # zip and CSV downloads
│       ├── routes.py             # /api/<experiment>/... for each, /api/experiments for all
│       └── toolbox/              # Docker build context (inference server + client), and marble/: the MARBLE code
│                                 # marble_infra.py, marble_endpoint.py: run MARBLE with the database tool or the
│                                 # search and read tools; marble_launch.py: what both share, and how a small
│                                 # model is got to call them (all mounted into the agents' container, not built in)
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

To use another Python environment instead (e.g. conda), install the dependencies there with `pip install -r api/requirements.txt` and set `PYTHON` to its interpreter when starting: `PYTHON=python npm run dev`.

## Run

```bash
npm run dev         # Next.js on :3000 + FastAPI on :8000
```

Open http://localhost:3000. API docs: http://localhost:3000/api/docs.

`dev:api` restarts FastAPI whenever a file in `api/` changes, which cancels a running experiment. For long experiments run the API without reload in its own terminal: `npm run start:api` together with `npm run dev:next`. On a remote server, start the app inside `tmux` so it keeps running when the SSH connection drops.

## Using it

The sidebar has two sections. **SI Traffic Analysis** lists six experiments, one prompt and its streamed response per capture: the five from the repo (Data Collector, Temperature Change, Custom Prompts, Scalability and Delay) and the Custom Experiment, which you set up yourself. **Agentic SI Analysis** lists the experiments where several agents work on a task, one per kind of communication that is captured: Agent to LLM, Agent to Infrastructure and Agent to Endpoint (see [Agentic SI Analysis](#agentic-si-analysis)). Agent to Agents (agents that run apart from each other) and Agent to People (one agent, several people on a chat service) are listed but not in the app yet.

| Page | What it's for |
| --- | --- |
| **Overview** (`/`) | Totals, the runs in progress, host status (Docker, GPU memory), recent runs of every experiment |
| **_Experiment_ › Runs** | Every run of that experiment, newest first |
| **_Experiment_ › New run** | Pick a downloaded model (several on Scalability, one per scenario on the Custom Experiment), what the experiment compares (see below), the hardware (Auto, chosen GPUs, or CPU), the number of workers, prompts, repeats and max tokens |
| **Run page** | *Monitor*: queue position, live progress, what each worker is doing, log, Cancel. *Results*: the run's analytics, and every capture with its packets on the wire, prompt, response and a PCAP download. *Export files* downloads the whole run as a zip, *Metrics CSV* one row per capture (with the worker and GPU that made it). Finished runs can be deleted here or from the runs list |
| **Prompts** | The prompt library: the 60 built-in prompts plus your own, in your own categories. Add prompts here or from *New run*. Custom Prompts doesn't use it |
| **Settings** | Theme (light / dark / system) and accent color, the default sampling temperature, the results folder, HuggingFace token, model downloads and deletion |

Every run gets a number (#1, #2, …) shown as a colored badge. Numbers are shared by all experiments and never reused, so #7 always means the same run. A run can also have a name, set when starting it or later from its page.

### The experiments

All six run the same capture: a fresh inference container per prompt, a tcpdump sidecar, and a client on an isolated network. Data Collector and Custom Prompts capture every prompt once. The other four compare several settings in one run (up to 8, one chart color each) and capture every prompt once per setting.

| Experiment | A run compares | Defaults (from the original scripts) |
| --- | --- | --- |
| **Data Collector** | nothing: the baseline | all prompts, once |
| **Custom Prompts** | nothing. Its prompts are written in its *New run* form and saved with the experiment (`data/custom-prompts.json`), never in the prompt library. They are sent exactly as written, spaces and line breaks included. Results are broken down per prompt | the 10 crafted prompts of `4-Crafted-Prompts/main.py`, verbatim, 10 times each |
| **Temperature Change** | sampling temperatures, 0 to 2, on one model. The original edited `TEMPERATURE` in `inference_server.py` between runs; here the server gets `--temperature`. 0 is greedy decoding | all prompts, once, at 0.3, 0.7 and 0.9 |
| **Scalability** | models, smallest first. The original ran one model per invocation. GPU memory is reserved for the largest | the 10 Code Generation prompts, 10 times each |
| **Delay** | network conditions: a delay, a jitter and its distribution (`normal`, `pareto`, `paretonormal`). Before each capture, `tc qdisc add dev eth0 root netem delay …` runs from a netshoot sidecar in the inference container's network, as in `6-Delay/main.py`. It delays everything the server sends, so both the PCAP and the client's timing show it | the 10 Logical Reasoning prompts, 10 times each, with no delay and with 500 ms ± 50 ms |
| **Custom Experiment** | scenarios. It is not one of the repo's scripts: each scenario has its own model, sampling temperature and network condition (delay, jitter and distribution, applied as in Delay), so a run can repeat any of the other experiments, cross them (two models under a delay, a temperature sweep on each), or be one scenario with everything set by hand. A scenario can be given a label; otherwise the results name it by what sets it apart from the others (`Temperature 0.3`, or `Qwen2.5-7B-Instruct · T 0.3 · 500 ms` when several things differ). Its prompts come from the prompt library, or are written in its *New run* form and sent exactly as written, as in Custom Prompts (saved in `data/custom-experiment-prompts.json`) | one scenario: the first model, the default temperature, no delay. All prompts, once |

**Sampling temperature.** Data Collector, Custom Prompts, Scalability and Delay sample at the default temperature in Settings → Sampling (0.7 unless changed, as in the original scripts; 0 is greedy decoding). A run records the temperature it started with, so changing the setting only affects new runs. Temperature Change sets its own temperatures and ignores it. In a Custom Experiment every scenario has its own temperature, which starts at the default. In every case only the temperature is set: the model's own `generation_config.json` (top_p, top_k, repetition penalty) still applies, as in the original scripts.

The captures of a prompt's settings run one after the other (prompt 1 at every temperature, then prompt 2, …), so every setting sees the same conditions over the run and a cancelled run still has all of them. On the results page, the **By temperature / model / network condition / scenario** tile compares them metric by metric, and every chart has one series per setting.

The Delay experiment, and a Custom Experiment scenario with a delay, need the host kernel's `sch_netem` module (`sudo modprobe sch_netem`). If `tc` fails, the run stops with that hint instead of capturing without the delay. Jitter needs a delay, and a distribution only applies with jitter (iproute2 rejects it otherwise).

Runs are saved in the results folder (`data/` by default, changeable in Settings), so the history survives restarts; a run that was active when the API stopped shows as *interrupted*.

**Provider (every SI Traffic Analysis experiment).** *Hugging Face* is the app's own server loading a HuggingFace model with transformers, as in the original scripts. *Ollama* serves an Ollama model instead (`api/experiments/ollama_engine.py`): a fresh `ollama/ollama` container per prompt with the Ollama models folder mounted, and a client that loads the model, then streams `/api/generate`. The prompts, the isolated network, the capture and the results are the same. A run takes all its models from one provider, except the Custom Experiment: each of its scenarios has its own, set by the model picked, so one run can compare a model on the app's own server with one on Ollama. Keep in mind that the two servers stream their responses in different formats, so such a comparison measures the server as well as the model. Ollama models are downloaded in Settings → Ollama models; the app pulls them from the Ollama library itself (`api/settings/ollama_models.py`), so nothing has to be installed on the host. The `ollama/ollama` image is pulled on the first run and kept.

### Agentic SI Analysis

**Agent to LLM** runs [MARBLE](https://github.com/pooryousefshahrooz/marble-traffic-dataset) tasks: several agents (usually 3 to 5) work on a task, and every LLM call of every agent goes to one Ollama server. Those calls are the only traffic captured: the agents pass each other messages inside MARBLE's process, never over the network.

The **coordination topology** is an option of the run. In *graph*, every agent plans its own next step; in *star*, a central planner assigns each agent its work. A run captures each task once under every topology chosen, with the same agents and model, so a task fingerprint learned under one can be tested on the other. (The experiment was first called Topology Transfer, and its address and results folder still are `topology-transfer`, so earlier runs stay listed.)

The MARBLE code ships with the API, in `api/experiments/toolbox/marble/`, so it goes wherever `api/` is deployed. It is a copy of [pooryousefshahrooz/marble-traffic-dataset](https://github.com/pooryousefshahrooz/marble-traffic-dataset) at commit `551e071` (2026-07-17), MIT license (`LICENSE` in that folder); its own `README.md` describes the fork. It is a snapshot, not a submodule: to update it, copy the folder again from that repository. Left out of the copy: the tree and chain task configs (not collected for the dataset), MARBLE's demo configs for its database and Minecraft scenarios (`marble/configs/test_config_database`, `test_config_minecraft`, `coding_configs`), its tests, CI files, images and lock file, and `.env.template`.

Before the first run, download an Ollama model in Settings → Ollama models (the dataset was collected with `llama3.2:3b`).

How a run captures (`api/experiments/marble_engine.py`, ported from `toolbox/marble/scripts/capture_marble_dataset.py`):

- Each worker keeps an Ollama container with the model loaded, on its own isolated network, and a TLS proxy sharing Ollama's network namespace. Ollama listens on its loopback only, so the proxy's port (11443) is the only thing on the network and everything on it is TLS. Before its first task, a worker makes one call to the model from the agents' image; if that fails, the run stops with the reason.
- Per task: a tcpdump sidecar on that namespace, then MARBLE in a fresh container (image built from `toolbox/marble/` by `toolbox/Dockerfile.marble`). The run saves the PCAP, `captures/<stem>.agent_calls.json` (which agent made each call and when, in the dataset's format), the task's config as it ran and MARBLE's output.
- A task that doesn't finish in 300 s, or that MARBLE doesn't complete, is kept and marked *not completed*; it is left out of the medians and the heatmap. Three in a row stop the run.
- MARBLE's own database tasks (the diagnosis of a slow database: they start PostgreSQL with `docker compose` and load it for minutes before any agent acts) and its research tasks (they fetch papers from the internet) can't run in the agents' container and are disabled. Agent to Infrastructure is the app's database experiment.

Unlike the original, which captured on the host's loopback, the capture is taken on the model server's network interface, so packet sizes are not directly comparable with the published dataset's.

**Results** are measured as in the dataset's analysis, over the encrypted application packets of every connection of a task: packets, bytes, duration, packet rate, bursts and idle time, plus the LLM calls and agents. The **Traffic by task category** tile is the dataset's heatmap for each topology: each measurement's median per category, standardized across the categories. A capture's page shows each agent's calls over time and the packets from the model server.

**The dataset's figures on a run.** The plots bundle that came with the dataset has four MARBLE figures; an agentic run's results page draws each from the run's own captures:

- *Traffic heatmap* → **Traffic by task category**, as above.
- *Traffic distributions* → **By task category**: a box per category and topology for the measurement you pick (bytes, duration, packets…), over the tasks (a task counts once, by the median of its repetitions), on a log axis.
- *Topology transfer* → **Task fingerprinting**: the balanced accuracy of a Random Forest that predicts the task category from 247 measurements of a capture's packets, tested on tasks it has not seen. Trained on each topology, it is tested on that topology's held-out tasks and on the same tasks under the other topology.
- *Agent visibility* → **Agent visibility**: the same accuracy when only the packets of 1, 2, 3… agents are seen.
- *Feature importance* → **What the classifier relies on**: the ten measurements the forests lean on most, by name, per topology.

The classifier is `api/experiments/marble_classifier.py`. The 247 measurements are the dataset's (`features_from_arrays`, ported line for line and checked against the bundle's feature table on the dataset's captures: identical). The forests have the bundle's settings (150 trees, balanced classes) and its folds: five, split by task, so a task's repetitions are never on both sides. Where the bundle spends hours, this is lighter: no hyperparameter search per fold, importances from the five fold forests instead of fifty, three random agent orderings instead of ten, and no sweep over random feature subsets (its accuracy against 3, 6, 10, 50 and 100 features).

- It needs `numpy` and `scikit-learn` (in `api/requirements.txt`). The API runs without them, and the tile says they are missing.
- It is trained once, when the run has finished, in a background thread, and saved in the run's `analysis/` folder. It waits while any run is capturing, so that training doesn't change the timings being captured.
- It needs at least 3 completed tasks in every category under every topology (5 for the full five folds), and two categories. A smaller run shows why there is no classifier.

**Agent to Infrastructure** captures another of the agents' connections: the one to a database they work on. The agents, the model, the topologies and the Ollama server are the same as in Agent to LLM; what is added (`api/experiments/infra_engine.py`):

- **The database** is a mock online store in PostgreSQL (`api/experiments/store_db.py`): customers, products, orders, order items and support tickets, the same rows every time (a fixed seed). Each task gets a new `postgres:16` container on its worker's isolated network, reachable by the agents under its container name. PostgreSQL creates the tables and rows during its own start-up, before it listens on the network, so none of that is in a capture. The container is removed after the task. The seed script is saved with the run (`configs/database/store.sql`).
- **The tasks** are requests on the store, 15 in each of five categories by what they do to the database: *lookup* (read one row or a few), *insert*, *update*, *delete* and *report* (read and summarize many rows). The same three agents work on every task: one writes the statement, one looks up the rows it involves, one checks the result. The request names rows that exist ("Mark order 102 as shipped").
- **The agents' tool** is `query_db(sql)`. It is added to MARBLE by `toolbox/marble_infra.py`, which is mounted into the agents' container with `toolbox/marble_launch.py` and run in place of MARBLE's `main.py`; the MARBLE code itself is not changed. Every call opens its own TLS connection to the database (PostgreSQL's TLS, with the image's self-signed certificate), runs the statement and saves it right away, so a query is one connection in the capture. MARBLE's own database environment is not used: it is built for diagnosing a slow database, starts PostgreSQL itself on localhost and rolls back a statement that changes rows.
- **The capture** is taken on the database's network interface, so it holds the agents' traffic with the database and nothing else. Their calls to the model go to another container and are not in it. Beside the PCAP the run saves `captures/<stem>.tool_calls.json` (which agent ran each statement, when, the statement, whether the database refused it and how many rows it returned or changed) and `captures/<stem>.agent_calls.json` (their LLM calls, as in Agent to LLM).
- **Results** are the same measurements over the database connection, with the task categories being the kinds of request. A capture's page shows each agent's queries over time, the statements and the packets from the database. The two packets PostgreSQL exchanges in the clear before TLS starts are left out, like the TLS handshake.

The model has to write SQL that runs, and three agents share one database: a small model will repeat a statement or have one refused. Those queries are traffic too, and each is recorded with its outcome.

**Agent to Endpoint** captures the agents' connections to public websites. **It is the one experiment whose containers reach the internet**; every other experiment runs on a Docker network without it. What is added to Agent to LLM (`api/experiments/endpoint_engine.py`):

- **The tasks** are requests the agents answer from what they find online, 15 in each of three categories by what they look up: *papers* (arXiv), *medical* (MedlinePlus health topics) and *security* (vulnerabilities and their advisories). Pick two categories for a two-class comparison. The same three agents work on every task: one searches, one reads, one checks against a second page. The security tasks are of three kinds: what CISA requires for an exploited vulnerability against the vendor's advisory, the version of an open source package that fixes one, and a subject that takes two records to answer.
- **The agents' tools** are `search(query)` and `read(url)`, the same two whatever the category, each one HTTPS request on a connection of its own. They are added to MARBLE by `toolbox/marble_endpoint.py`, mounted like the database launcher. Where they go:

  | Category | `search` | `read` |
  |---|---|---|
  | Papers | arXiv's API (`export.arxiv.org/api/query`) | the paper's record from the same API |
  | Medical | MedlinePlus search (`wsearch.nlm.nih.gov`) | the topic's page on `medlineplus.gov` |
  | Security | the National Vulnerability Database's API (`services.nvd.nist.gov`); with the word *exploited* in the query, only the vulnerabilities in CISA's Known Exploited Vulnerabilities catalog, whose entries NVD carries | the vulnerability's NVD record (with CISA's required action), its OSV record (`api.osv.dev`: the open source package and the versions that fix it), or an advisory page the record links, on the vendor's own site |

- **Manners.** The requests say what they are (`RogueAgent-research/0.1 (encrypted traffic study)`; set `MALLM_ENDPOINT_USER_AGENT` on the API's host to add a way to reach you) instead of posing as a browser. They go out one at a time, with the pause each service asks for: three seconds for arXiv's API, six and a half for NVD's (it takes five requests in thirty seconds without a key; with `MALLM_NVD_API_KEY` set on the API's host, fifty), one for the others. That is why a run has **one worker**. `read` only opens an address the tools gave during the task, and for a web page only when the site's robots.txt leaves it open to programs, asked once per site. A site that refuses is not worked around: the agent is told the page can't be read. Of a vulnerability's links, only those NVD tags as the vendor's advisory, a patch, release notes or a mitigation are offered, and not the ones it tags as broken or behind a login.
- **The capture** is taken on the agents' side: each worker keeps a small container that only owns a network interface, the tcpdump sidecar listens on it, and every task's agents run inside it. So a PCAP holds everything the agents sent and received: their requests to the sites (port 443, what the results measure) and their calls to the model (the worker's proxy, port 11443). Name lookups are answered by Docker inside the container and are not in it. Beside the PCAP the run saves `captures/<stem>.tool_calls.json`: which agent made each request, when, what it asked for and whether it failed.
- **Before its first task** a worker checks from the agents' image that the internet is reachable, and the run stops with the reason if it is not.
- **Results** are the same measurements over the connections to the sites, with the categories being what the agents looked up.

What a capture holds depends on the sites: on what they answer that day and how fast. Two runs of the same task are not the same bytes. The sources also differ in how much they send: in a scripted sample, a papers task moved 20 to 50 KB and a security task 15 to 45 KB (both are answers from an API), a medical one 85 to 300 KB (whole pages). So medical stands apart by volume alone, while papers and security overlap and have to be told apart by timing and packet patterns. Keep runs modest in size: the sites are not ours to load.

Two limits of the security category as it stands. Most large vendors publish their advisories on pages that scripts fill in, so a plain request gets a page without text: of the first advisory link of the five exploited-vulnerability tasks, Apache's could be read, Citrix's, Microsoft's and Ivanti's had no text without a browser, and Fortinet's did not answer. The request is still made and captured, and the agent is told the page can't be read; a comparison with the vendor's own words mostly needs the browser mode this experiment does not have yet. And NVD returns a search's results oldest first, with no way to ask for another order, so a broad query ("OpenSSL") brings records from the 2000s whose links are often dead.

Sources that were tried and are not used, so that they are not tried again: CISA's own site refuses programs (its catalog page answers 403 and its robots.txt closes everything; its entries come through NVD); DuckDuckGo's plain search page answered one automated query and refused the next fourteen; Stack Overflow's pages answer programs with a human-verification page; GeeksforGeeks articles can be read but its search is closed to programs, and a programming category built on it was replaced by the security one.

**Getting a small model to use its tools.** MARBLE asks the model for an action with `tool_choice: auto`, and through Ollama that is a request for JSON: only an answer shaped `{"name": ..., "arguments": {...}}` counts as a tool call. A 3B model often gets close without getting there (`{"sql": "SELECT ..."}`, a statement in a code fence, a sentence naming the page), MARBLE then carries on, and the task ends with a capture that holds nothing. Agent to Infrastructure and Agent to Endpoint do four things about it, all in `toolbox/marble_launch.py`, without changing MARBLE:

1. **Before a worker's first task**, the model is asked for one tool call the way an agent would ask (`--check-model`). If it can't, the run stops there with what the model answered, instead of after three empty tasks.
2. **An answer that is a call in all but shape is read as one**: the arguments alone, another spelling of the envelope (`function`, `parameters`), or what only one tool could be given: a SQL statement that starts a line, an address the tools returned.
3. **Otherwise the model is asked once more**, shown its answer and the exact shape wanted.
4. **The agents' profiles say it** in every prompt: each agent always answers with a call to its tool.

A call made the second or third way is marked in `tool_calls.json` (`origin`: `recovered` or `asked again`) and under the statement on a capture's page, and counted in the task's result, so those calls can be left out of an analysis. What this can't fix is a model that answers in prose both times. Such a task is kept and still shown, but three in a row stop the run: a task whose agents called no tool, or whose every statement the database refused, or whose every request failed.

### Workers, parallel runs and the queue

- **Workers.** A run can have several workers. Each is its own model instance with its own containers, its own isolated Docker network and its own packet capture. The captures are divided evenly and fixed when the run starts: worker 1 takes the 1st, 3rd, 5th… capture and worker 2 the 2nd, 4th, 6th…, so 6 prompts on 2 workers is 3 each, and no prompt category ends up on only one GPU. With several settings (temperatures, models, conditions), each setting's captures are dealt out the same way, starting one worker further along per setting, so every setting runs on every GPU and the settings of one prompt run side by side. Every capture is still one prompt in a fresh container.
- **Choose GPUs** (the default when the host has several). *One copy per GPU*: every selected GPU runs its own worker (or several, with *Workers per GPU*), so 2 GPUs run 2 copies of the model side by side. *Split one copy across them*: every worker's model is spread over all the selected GPUs, for models too large for one GPU.
- **Auto** spreads the workers over the GPUs with free memory: the GPU with the fewest of the run's workers first, then the one with the most room.
- **Parallel runs.** Several runs can be active at once, of any experiment. Each has its own container names and networks, and they share one queue and one view of GPU memory.
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

Results are cached per capture in `analysis/` next to the PCAPs and rebuilt if a PCAP changes. The metrics CSV has one row per capture, with the setting it was captured with (`temperature`, `model`, or `delay_ms`, `jitter_ms`, `distribution`; all of them and `scenario`, its label, for a Custom Experiment).

## Docker cleanup

Everything a run creates is labeled `mallm.<experiment>.run=<run id>` (e.g. `mallm.temperature-change.run`). When the run ends (completed, failed or cancelled), it removes:

- its containers (inference servers, tcpdump and netem sidecars, clients)
- its Docker networks: `mallm-<run id>`, or `mallm-<run id>-w1`, `-w2`, … with several workers
- the `mallm-llm-toolbox:<run id>` image it built
- images the app had to pull (the base image, `nicolaka/netshoot`). These are shared by concurrent runs of every experiment, so the last run to finish removes them

Nothing without that label is touched. If the API process dies mid-run, the next start of the API removes the leftovers. Docker's build cache is kept, so the next build takes seconds instead of reinstalling torch.

## Outputs

`<experiment>` is `data-collector`, `temperature-change`, `custom-prompts`, `scalability`, `delay` or `custom-experiment`.

| Path                                   | Contents                                               |
| -------------------------------------- | ------------------------------------------------------ |
| `data/<experiment>/<run id>/captures` | PCAP per capture: `<model>-pNN.pcap` as in the original scripts, `<model>-t0.7-pNN.pcap` for a temperature, `<model>-d500ms-j50ms-normal-pNN.pcap` for a network condition, `<model>-t0.7-d500ms-j50ms-normal-pNN.pcap` for a scenario (`-d0ms` without a delay) |
| `data/<experiment>/<run id>/results`  | client output per capture: response + per-event timing, its setting, and the worker and GPUs that ran it |
| `data/<experiment>/<run id>/logs`     | prompt text, model response and server logs            |
| `data/<experiment>/<run id>/analysis` | cached analytics per capture                           |
| `data/<experiment>/<run id>/run.json` | the run's settings, what it compares, its temperature, status and cleanup report |
| `data/<experiment>/<run id>/prompts.json` | the prompts the run was created with (text and category). Results are read against these, so editing a prompt later never changes a past run |
| `data/<experiment>/<run id>/run.log`  | the run's full log                                     |
| `data/prompts.json`                    | your prompts (numbered from 61; numbers are never reused) |
| `data/custom-prompts.json`             | the Custom Prompts experiment's saved prompts (the crafted ones until you change them) |
| `data/custom-experiment-prompts.json`  | the Custom Experiment's written prompts (none until you write some) |
| `data/settings.json`                   | saved settings: results folder, default temperature, HF token (owner-only) |
| `models/<org>-<name>`                  | downloaded models                                      |

## Configuration

| Variable           | Default                 | Description                                                    |
| ------------------ | ----------------------- | -------------------------------------------------------------- |
| `MALLM_MODELS_DIR` | `models/`               | Downloaded models. Point it at an existing models folder to reuse it. |
| `MALLM_DATA_DIR`   | `data/`                 | Settings, prompts, and experiment outputs unless another results folder is set in Settings. |
| `MALLM_OLLAMA_DIR` | `ollama_models/` (next to the models folder) | Ollama models, in Ollama's own layout. Mounted into the Ollama containers as `/root/.ollama`. |
| `MALLM_MARBLE_DIR` | `api/experiments/toolbox/marble/` | The MARBLE code the agentic experiments run. |
| `MALLM_ENDPOINT_USER_AGENT` | `RogueAgent-research/0.1 (encrypted traffic study)` | How Agent to Endpoint's requests name themselves to the sites. Add a contact address. |
| `MALLM_NVD_API_KEY` | none | A key for the National Vulnerability Database's API (free, from nvd.nist.gov). Agent to Endpoint's security lookups then wait 0.7 s between two instead of 6.5. |
| `HF_TOKEN`         | none                    | HuggingFace token, used when none is saved in Settings.        |
| `PYTHON` | `.venv/bin/python` | Python that runs the FastAPI backend. Set it to use a conda or other environment, e.g. `PYTHON=python` after `conda activate`. |
| `API_PORT` | `8000` | Port of the FastAPI backend. Used by the `dev:api`/`start:api` scripts *and* by Next.js to forward `/api/*`, so set it for both (e.g. `API_PORT=8007 npm run dev`). |
| `API_URL` | `http://127.0.0.1:$API_PORT` | Full address Next.js forwards `/api/*` to, if the backend is on another host. Read at build time for `next build`. |
