"""
Agent to Endpoint: several agents answer a request by looking it up on the web, and their
connections to those sites are what is captured.

The tasks are grouped by what the agents look up, each kind on its own public sources:
research papers (arXiv), health topics (MedlinePlus) and security advisories (the National
Vulnerability Database with CISA's Known Exploited Vulnerabilities entries, OSV for open
source packages, and the vendors' own advisory pages). The agents have two tools for every
kind, search(query) and read(url), each one HTTPS request (toolbox/marble_endpoint.py). The
agents, the model and the two coordination topologies are MARBLE's, as in Agent to LLM,
and endpoint_engine.py runs them.

It is the one experiment whose containers reach the internet: every other one runs on a
network without it. The captures therefore depend on those sites: on what they answer
that day and how fast.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import model_validator

from . import marble_common as common
from .base import Kind, Link, RunConfig

ENV_TYPE = "Endpoint"   # the environment toolbox/marble_endpoint.py adds to MARBLE

# What the agents look up: (label, what the form says about it, what the agents are told the tools reach)
CATEGORIES: dict[str, tuple[str, str, str]] = {
    "papers": ("Papers", "Research papers on arXiv", "research papers on arXiv"),
    "medical": ("Medical", "Health topics on MedlinePlus", "health topics on MedlinePlus, from the U.S. National Library of Medicine"),
    "security": ("Security", "Vulnerabilities and their advisories",
                 "vulnerabilities in the U.S. National Vulnerability Database (put the word exploited in the query to search "
                 "only CISA's Known Exploited Vulnerabilities catalog)"),
}

# Every site is reached over HTTPS: the capture's traffic is what goes to or from port 443.
# The agents' calls to the model, in the same capture, go to the proxy's own port.
WEB_LINK = Link(port=443, calls="tool_calls")

_PAPERS = [
    "website fingerprinting attacks on encrypted traffic", "retrieval augmented generation for question answering",
    "federated learning with differential privacy", "graph neural networks for traffic forecasting",
    "prompt injection attacks on language models", "diffusion models for image generation",
    "reinforcement learning for robot manipulation", "transformers for time series forecasting",
    "adversarial examples in image classification", "language model agents that use tools",
    "anomaly detection for network intrusion", "quantization of neural networks for edge devices",
    "contrastive learning of sentence embeddings", "cooperation in multi-agent reinforcement learning",
    "side channel attacks on machine learning models",
]
_CONDITIONS = [
    "asthma", "type 2 diabetes", "migraine", "high blood pressure", "iron deficiency anemia", "seasonal allergies",
    "kidney stones", "pneumonia", "osteoarthritis", "acid reflux (GERD)", "insomnia", "urinary tract infections",
    "eczema", "hypothyroidism", "concussion",
]
# Security advisories, in three kinds: what CISA says about an exploited vulnerability against the vendor's
# advisory, the version of an open source package that fixes one, and a subject that takes two records
_EXPLOITED = ["Citrix NetScaler", "Apache Log4j", "Microsoft Exchange Server", "Fortinet FortiOS", "Ivanti Connect Secure"]
_PACKAGES = ["Django", "OpenSSL", "lodash", "Apache Struts", "curl"]
_SUBJECTS = [
    "an implementation of the Kyber post-quantum key exchange", "certificate validation in a TLS library",
    "deserialization of untrusted data in Java", "a SQL injection in a WordPress plugin",
    "a buffer overflow in a router's firmware",
]
TASKS: dict[str, list[str]] = {
    "papers": [f"Find a recent research paper about {topic} and say in two sentences what it proposes." for topic in _PAPERS],
    "medical": [f"Look up {condition}: what are its main symptoms and how is it usually treated?" for condition in _CONDITIONS],
    "security": [
        *(f"Find a vulnerability in {product} that is in CISA's Known Exploited Vulnerabilities catalog. Compare what CISA "
          "requires with the vendor's advisory, and summarize the affected products and the mitigation." for product in _EXPLOITED),
        *(f"Find a security advisory for the open source package {package} and say which version fixes it, checking the "
          "version against the package's own record." for package in _PACKAGES),
        *(f"Find two reported vulnerabilities about {subject}. Say whether they are the same underlying problem, naming both "
          "records." for subject in _SUBJECTS),
    ],
}
assert all(len(requests) == common.TASKS_PER_CATEGORY for requests in TASKS.values())

# The same three agents for every task; under the star topology MARBLE's planner hands them their work
AGENTS = [
    ("agent1", "agent1 is the researcher. agent1 finds pages about the request with the search tool. agent1 always answers "
               "with a call to search or read, never from memory."),
    ("agent2", "agent2 is the reader. agent2 opens the most relevant address that search found with the read tool and notes "
               "what in it answers the request. agent2 always answers with a call to read or search, never from memory."),
    ("agent3", "agent3 is the reviewer. agent3 opens a second address with the read tool to check the answer, and reports "
               "it. agent3 always answers with a call to read or search, never from memory."),
]


class EndpointConfig(common.TaskRunConfig):
    @model_validator(mode="after")
    def _one_worker(self) -> EndpointConfig:
        # The sites limit the requests they take from one address, and each worker would add its own
        if (self.workers or 1) > 1:
            raise ValueError("Agent to Endpoint runs with one worker, so that the sites get one request at a time.")
        self.workers = 1
        return self


def prompts(config: EndpointConfig) -> dict[int, dict]:
    return common.prompts(config, {slug: label for slug, (label, _, _) in CATEGORIES.items()}, TASKS, len(AGENTS))


def task_text(category: str, request: str) -> str:
    """What the agents are given: what the tools reach, then the request."""
    return (
        f"Answer the request below from what you find online. You have two tools: search(query) finds {CATEGORIES[category][2]} "
        "and returns their titles and addresses, and read(url) opens one of the addresses that search returned.\n\n"
        f"Request: {request}\n\n"
        "Search first, then read the most relevant results, then answer from what they say."
    )


def task_config(task: dict, topology: str, model: str) -> str:
    return common.task_config(
        scenario="endpoint", task=task, topology=topology, model=model,
        environment={"type": ENV_TYPE, "name": "Endpoint Environment", "source": task["marble_category"]},
        content=task_text(task["marble_category"], task["text"]),
        output_format="Answer the request in a few sentences and name the page the answer comes from.",
        agents=AGENTS,
    )


def _runner(config: RunConfig) -> type:
    from .endpoint_engine import EndpointExperiment   # imports the engine, which imports the kinds
    return EndpointExperiment


KIND = Kind(
    slug="agent-to-endpoint",
    title="Agent to Endpoint",
    config=EndpointConfig,
    variants=common.variants,
    variable="Topology",
    prompts=prompts,
    check=common.check,
    runner=_runner,
    sampled=False,
    link=WEB_LINK,
)


# ── What the New run form needs ──────────────────────────────────────────────

router = APIRouter(prefix=f"/{KIND.slug}", tags=[KIND.title])


@router.get("/tasks")
def tasks() -> dict:
    """The kinds of lookup and the topologies a run can use, and whether the MARBLE code is in place."""
    return common.catalog(
        f"What the agents look up, each kind on its own public site. The same {len(AGENTS)} agents work on every task, "
        "with a search tool and a read tool.",
        {slug: (label, about) for slug, (label, about, _) in CATEGORIES.items()},
        max_workers=1,
        notice="These runs reach real websites: it is the only experiment whose containers have internet access. "
               "Requests are spaced out and sent one at a time, so a run has one worker, and what is captured depends "
               "on what the sites answer that day. Keep runs modest in size: the sites are not ours to load.",
    )
