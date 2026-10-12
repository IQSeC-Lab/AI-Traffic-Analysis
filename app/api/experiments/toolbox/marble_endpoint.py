"""
Runs a MARBLE task whose agents look things up on the web (Agent to Endpoint). Mounted
into the agents' container with marble_launch.py and run in place of marble/main.py:

    python /marble_endpoint.py --config_path /configs/<task>.yaml
    python /marble_endpoint.py --check-model      # one tool call asked of the model, before a run

A task config asks for the environment with
`environment: {type: Endpoint, source: papers | medical | security}`. The agents get two
tools whatever the source, each one HTTPS request on a connection of its own:

    search(query)   results on the task's source: titles, addresses and a few words of each
    read(url)       the text of an address that search (or a page read before) gave

Where they go:
    papers     arXiv's API (export.arxiv.org/api/query), for both: read fetches the paper's record
    medical    MedlinePlus: its search service (wsearch.nlm.nih.gov), then the topic's page
    security   vulnerabilities: search is the U.S. National Vulnerability Database's API, which
               also carries CISA's Known Exploited Vulnerabilities entries; read opens a
               vulnerability's NVD record, its OSV record (open source packages and the
               versions that fix them), or an advisory page of the vendor that the record links

Manners, the same for every source:
  - The requests say what they are (MARBLE_ENDPOINT_USER_AGENT) instead of posing as a browser.
  - They go out one at a time, with the pause each host asks for between two.
  - read only opens an address the tools gave during this task, and for a web page only when
    the site's robots.txt leaves it open to programs. A site that refuses is not worked
    around: the agent is told the page can't be read.
"""

import os
import re
import threading
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from marble_launch import ToolEnvironment, main

ENV_TYPE = "Endpoint"
USER_AGENT = os.environ.get("MARBLE_ENDPOINT_USER_AGENT") or "RogueAgent-research/0.1 (encrypted traffic study)"
ROBOT_NAME = USER_AGENT.split("/")[0]
NVD_KEY = os.environ.get("MARBLE_NVD_API_KEY")
TIMEOUT = 20          # seconds for a site to answer
MAX_RESULTS = 5
SNIPPET_CHARS = 220
READ_CHARS = 2500     # of a page's text given back to the agent
MIN_PAGE_CHARS = 200  # less text than this in a page: it is built by scripts, which a plain request doesn't run

ARXIV_API = "https://export.arxiv.org/api/query"
MEDLINE_SEARCH = "https://wsearch.nlm.nih.gov/ws/query"
NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
OSV_API = "https://api.osv.dev/v1/vulns/"
NVD_PAGE = "https://nvd.nist.gov/vuln/detail/"
OSV_PAGE = "https://osv.dev/vulnerability/"
# Seconds between two requests to a host. arXiv's API asks for three; NVD's takes five requests
# in thirty seconds without a key and fifty with one; the others get MARBLE's own one second.
PAUSE = {"export.arxiv.org": 3.0, "services.nvd.nist.gov": 0.7 if NVD_KEY else 6.5}
DEFAULT_PAUSE = 1.0
# Services made to be called by programs: their robots.txt is about their web pages
APIS = {"export.arxiv.org", "wsearch.nlm.nih.gov", "services.nvd.nist.gov", "api.osv.dev"}

SOURCES = ("papers", "medical", "security")
# Words that say nothing about what is looked for
COMMON = {"a", "an", "the", "in", "to", "of", "with", "how", "and", "by", "its", "do", "is", "for", "or", "on", "using", "use",
          "whether", "find", "out", "give", "that", "this", "about", "what", "are", "from", "recent", "recently", "research",
          "paper", "papers", "which", "it", "has", "have"}
# In a search for vulnerabilities: words that ask for CISA's catalog, and words every record has
EXPLOITED = {"exploited", "kev", "cisa"}
GENERIC = {"vulnerability", "vulnerabilities", "security", "advisory", "advisories", "catalog", "known", "added", "cve", "issue",
           "flaw", "bug", "package", "open", "source", "fixed", "version", "affects", "affecting", "affected", "product"}
# The links of a vulnerability's record worth opening, by how NVD tags them
USEFUL_LINKS = {"Vendor Advisory", "Patch", "Release Notes", "Mitigation"}
DEAD_LINKS = {"Broken Link", "Permissions Required"}
# Where an open source project's code, packages or advisories live
OPEN_SOURCE_HOSTS = ("github.com", "gitlab.com", "npmjs.com", "pypi.org", "rubygems.org", "crates.io", "pkg.go.dev",
                     "apache.org", "openssl.org", "curl.se", "djangoproject.com", "kernel.org")

TOOLS = {
    "search": {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search for pages about a subject. Returns up to five results, each with its number, its title, "
                           "its address (url) and a few words of it. Example: {\"query\": \"asthma treatment\"}",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "A few words on what to look for."}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    "read": {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Open an address that search returned, or one named in a page already read, and get its text.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "The address (url) of a search result, as search returned it, or the result's number."}},
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
}

_last_request: Dict[str, float] = {}
_request_lock = threading.Lock()   # one request at a time, whichever agent makes it
_robots: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}


class Closed(Exception):
    """The site doesn't take this request from a program."""


def _clean(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9+#.-]*[a-z0-9+#]", text.lower())


def _get(url: str, params: Optional[dict] = None, sent: Optional[List[float]] = None, check: bool = True) -> requests.Response:
    """One request on a connection of its own, after the pause its host is owed."""
    host = urlparse(url).hostname or ""
    headers = {"User-Agent": USER_AGENT, **({"apiKey": NVD_KEY} if NVD_KEY and host == "services.nvd.nist.gov" else {})}
    with _request_lock:
        wait = PAUSE.get(host, DEFAULT_PAUSE) - (time.time() - _last_request.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        if sent is not None:
            sent.append(time.time())
        try:
            response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        finally:
            _last_request[host] = time.time()
    if check:
        response.raise_for_status()
    return response


def _open_to_programs(url: str, sent: List[float]) -> bool:
    """Whether the site's robots.txt lets a program read this page. Asked once per site."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in APIS:
        return True
    if host not in _robots:
        rules: Optional[urllib.robotparser.RobotFileParser] = urllib.robotparser.RobotFileParser()
        try:
            answer = _get(f"https://{host}/robots.txt", sent=sent, check=False)
            if answer.status_code in (401, 403) or answer.status_code >= 500:
                rules = None                        # the site turns programs away altogether
            elif answer.status_code >= 400:
                rules.parse([])                     # no robots.txt: nothing is closed
            else:
                rules.parse(answer.text.splitlines())
        except requests.RequestException:
            rules = None
        _robots[host] = rules
    rules = _robots[host]
    return rules is not None and rules.can_fetch(ROBOT_NAME, url)


# ── Papers: arXiv ────────────────────────────────────────────────────────────

def _arxiv(params: dict, sent: List[float]) -> List[dict]:
    atom = {"a": "http://www.w3.org/2005/Atom"}
    found = []
    for entry in ET.fromstring(_get(ARXIV_API, params, sent).content).findall("a:entry", atom):
        address = (entry.findtext("a:id", "", atom) or "").replace("http://", "https://")
        if "/abs/" in address:
            found.append({"title": _clean(entry.findtext("a:title", "", atom), 200), "url": address,
                          "text": _clean(entry.findtext("a:summary", "", atom), READ_CHARS)})
    return found


def search_papers(query: str, sent: List[float]) -> List[dict]:
    # Every word has to be in the paper's record, so only the few that carry the subject are sent
    terms = [w for w in _words(query) if len(w) > 2 and w not in COMMON][:4] or _words(query)[:4]
    found = _arxiv({"search_query": " AND ".join(f"all:{w}" for w in terms), "start": 0, "max_results": MAX_RESULTS,
                    "sortBy": "relevance"}, sent)
    return [{"title": f["title"], "url": f["url"], "snippet": _clean(f["text"], SNIPPET_CHARS)} for f in found]


def read_paper(address: str, sent: List[float]) -> Tuple[str, List[str]]:
    # The paper's record from the API, the way arXiv asks programs to read it
    found = _arxiv({"id_list": address.rstrip("/").rsplit("/abs/", 1)[-1], "max_results": 1}, sent)
    if not found:
        raise ValueError("arXiv has no paper at that address")
    return f"{found[0]['title']}. Abstract: {found[0]['text']}", []


# ── Medical: MedlinePlus ─────────────────────────────────────────────────────

def search_medical(query: str, sent: List[float]) -> List[dict]:
    root = ET.fromstring(_get(MEDLINE_SEARCH, {"db": "healthTopics", "term": query, "retmax": MAX_RESULTS}, sent).content)
    found = []
    for document in root.iter("document"):
        content = {c.get("name"): c.text or "" for c in document.iter("content")}
        found.append({"title": _clean(content.get("title", ""), 200), "url": document.get("url", ""),
                      "snippet": _clean(content.get("FullSummary") or content.get("snippet", ""), SNIPPET_CHARS)})
    return found


# ── Security: NVD (with CISA's exploited catalog), OSV, vendors' advisories ──

def _links(cve: dict) -> List[str]:
    """The record's links worth opening, the vendor's own advisory first and mailing lists last."""
    found: Dict[str, tuple] = {}
    for reference in cve.get("references", []):
        tags = set(reference.get("tags") or [])
        address = reference.get("url", "")
        if tags & USEFUL_LINKS and not tags & DEAD_LINKS and address.startswith("https://") and address not in found:
            found[address] = ("Mailing List" in tags, "Vendor Advisory" not in tags)
    return sorted(found, key=lambda address: found[address])


def _description(cve: dict) -> str:
    return next((d.get("value", "") for d in cve.get("descriptions", []) if d.get("lang") == "en"), "")


def search_security(query: str, sent: List[float]) -> List[dict]:
    words = _words(query)
    # Asking for exploited vulnerabilities searches CISA's catalog only, which NVD carries
    params: Dict[str, Any] = {"resultsPerPage": MAX_RESULTS}
    if EXPLOITED & set(words):
        params["hasKev"] = ""
    terms = [w for w in words if w not in COMMON | EXPLOITED | GENERIC and len(w) > 1][:4]
    if terms:
        params["keywordSearch"] = " ".join(terms)
    found = []
    for item in _get(NVD_API, params, sent).json().get("vulnerabilities", []):
        cve = item.get("cve", {})
        exploited = (f" In CISA's Known Exploited Vulnerabilities catalog since {cve['cisaExploitAdd']}."
                     if cve.get("cisaExploitAdd") else "")
        advisories = "".join(f" | advisory: {address}" for address in _links(cve)[:2])
        found.append({
            "title": f"{cve.get('id')}: {cve.get('cisaVulnerabilityName') or _clean(_description(cve), 90)}",
            "url": NVD_PAGE + str(cve.get("id")),
            "snippet": _clean(_description(cve), SNIPPET_CHARS) + exploited + advisories,
            "links": _links(cve)[:2],
        })
    return found


def read_vulnerability(address: str, sent: List[float]) -> Tuple[str, List[str]]:
    number = address.rstrip("/").rsplit("/", 1)[-1].upper()
    found = _get(NVD_API, {"cveId": number}, sent).json().get("vulnerabilities", [])
    if not found:
        raise ValueError(f"The National Vulnerability Database has no record of {number}")
    cve = found[0]["cve"]
    parts = [f"{number}. {_clean(_description(cve), 900)}"]
    for metrics in cve.get("metrics", {}).values():
        data = (metrics[0] if metrics else {}).get("cvssData", {})
        if data.get("baseScore") is not None:
            parts.append(f"Severity: {data.get('baseSeverity', '')} {data['baseScore']}.".replace("  ", " "))
            break
    if cve.get("cisaExploitAdd"):
        parts.append(f"CISA's Known Exploited Vulnerabilities catalog: {cve.get('cisaVulnerabilityName', '')}, added "
                     f"{cve['cisaExploitAdd']}. Required action: {cve.get('cisaRequiredAction', '')} Due {cve.get('cisaActionDue', '')}.")
    affected = []
    for configuration in cve.get("configurations", []):
        for node in configuration.get("nodes", []):
            for match in node.get("cpeMatch", []):
                fields = match.get("criteria", "").split(":")
                if match.get("vulnerable") and len(fields) > 5:
                    fixed = match.get("versionEndExcluding")
                    line = f"{fields[3]} {fields[4]}" + (f" before {fixed}" if fixed else f" {fields[5]}" if fields[5] not in "*-" else "")
                    if line not in affected:
                        affected.append(line)
    if affected:
        parts.append("Affected: " + "; ".join(affected[:6]) + ".")
    links = _links(cve)[:4]
    if links:
        parts.append("Advisories: " + " , ".join(links) + " .")
    # OSV covers open source packages: its record is named only when the vulnerability's own links point to one
    offered = list(links)
    if any(host in reference.get("url", "") for reference in cve.get("references", []) for host in OPEN_SOURCE_HOSTS):
        parts.append(f"Its open source record, with the fixed versions: {OSV_PAGE}{number}")
        offered.append(OSV_PAGE + number)
    return " ".join(parts), offered


def read_advisory_record(address: str, sent: List[float]) -> Tuple[str, List[str]]:
    number = address.rstrip("/").rsplit("/", 1)[-1]
    answer = _get(OSV_API + number, sent=sent, check=False)
    if answer.status_code == 404:
        raise ValueError(f"OSV has no record of {number}: it covers open source packages")
    answer.raise_for_status()
    record = answer.json()
    parts = [f"{record.get('id')}. {record.get('summary') or ''} {_clean(record.get('details', ''), 600)}"]
    for package in record.get("affected", [])[:4]:
        name = package.get("package") or {}
        spans = package.get("ranges", [])
        # A record made from the source repository names commits; the versions are beside them when known
        events = [e for span in spans for e in (span.get("database_specific", {}).get("extracted_events") or span.get("events", []))]
        fixed = [str(e["fixed"])[:12] for e in events if "fixed" in e]
        what = (f"Package {name['name']} ({name.get('ecosystem')})" if name.get("name")
                else f"Source {next((span.get('repo') for span in spans if span.get('repo')), 'repository')}")
        parts.append(f"{what}: " + (f"fixed in {', '.join(dict.fromkeys(fixed[:4]))}." if fixed else "no fixed version listed."))
    # The same advisory under its other names: the one of the package's own ecosystem has its versions
    same = [OSV_PAGE + other for other in record.get("aliases", []) if other != number][:2]
    if same:
        parts.append("The same advisory as recorded for the package: " + " , ".join(same) + " .")
    links = [r["url"] for r in record.get("references", []) if r.get("type") in ("ADVISORY", "FIX") and r.get("url", "").startswith("https://")][:3]
    if links:
        parts.append("References: " + " , ".join(links) + " .")
    return " ".join(parts), [*same, *links]


# ── Any other page ───────────────────────────────────────────────────────────

def read_page(address: str, sent: List[float]) -> Tuple[str, List[str]]:
    if not _open_to_programs(address, sent):
        raise Closed("the site does not let programs read this page")
    page = BeautifulSoup(_get(address, sent=sent).text, "html.parser")
    for tag in page(["script", "style", "noscript", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()
    title = _clean(page.title.get_text() if page.title else "", 200)
    # Where the text itself is, without the site's menus
    body = page.select_one("#topic-summary") or page.find("article") or page.find("main") or page.body or page
    text = _clean(body.get_text(" "), READ_CHARS)
    if len(text) < MIN_PAGE_CHARS:   # a page that scripts fill in: there is nothing to read without a browser
        raise Closed("the page shows its text only in a browser")
    return f"{title}. {text}", []


class EndpointEnvironment(ToolEnvironment):
    SHAPE = ('{"name": "search", "arguments": {"query": "<a few words>"}}  or  '
             '{"name": "read", "arguments": {"url": "<the url of a search result>"}}')
    CHECK_PROMPT = ("You are agent1, the researcher. Your task: find a page about the symptoms of asthma. "
                    "You can solve the task by calling the search function.")

    def __init__(self, config: Dict[str, Any], name: str = "Endpoint Environment"):
        super().__init__(name, config)
        self.source = config.get("source") or ("medical" if config.get("check") else None)
        if self.source not in SOURCES:
            raise ValueError(f"Unknown source for the Endpoint environment: {self.source!r}")
        self.results: List[dict] = []       # of the last search
        self.offered: Dict[str, str] = {}   # every address the tools gave during the task, without its ending slash
        self.register_action("search", handler=self.search, description=TOOLS["search"])
        self.register_action("read", handler=self.read, description=TOOLS["read"])

    def label(self, action: str, arguments: Dict[str, Any]) -> str:
        return f"{action}: {arguments.get('query' if action == 'search' else 'url', '')}"

    def recover_text(self, text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        # An address the tools gave, written out instead of read
        named = [a for a in re.findall(r"https://[^\s\"'<>)\]]+", text) if a.rstrip("/.,") in self.offered]
        return ("read", {"url": named[0].rstrip(".,")}) if len(set(named)) == 1 else None

    def _offer(self, addresses: List[str]) -> None:
        for address in addresses:
            self.offered[address.rstrip("/")] = address

    def apply_action(self, agent_id: Optional[str], action_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        # A result named by its number is read, and logged, as its address
        asked = str(arguments.get("url", "")).strip() if isinstance(arguments, dict) else ""
        if action_name == "read" and asked.isdigit() and 1 <= int(asked) <= len(self.results):
            arguments = {**arguments, "url": self.results[int(asked) - 1]["url"]}
        return super().apply_action(agent_id, action_name, arguments)

    def search(self, query: str) -> Dict[str, Any]:
        try:
            found = {"papers": search_papers, "medical": search_medical, "security": search_security}[self.source](str(query), self._sent)
        except Exception as e:
            return {"status": "error", "function_name": "search", "rows": None,
                    "explanation": f"The search failed: {type(e).__name__}: {' '.join(str(e).split())[:300]}"}
        if not found:
            return {"status": "success", "function_name": "search", "rows": 0,
                    "explanation": "The search returned no result. Try other words, and fewer of them."}
        self.results = found
        self._offer([f["url"] for f in found] + [link for f in found for link in f.get("links", [])])
        lines = [f"{n}. {f['title']} | url: {f['url']}" + (f" | {f['snippet']}" if f["snippet"] else "") for n, f in enumerate(found, 1)]
        return {"status": "success", "function_name": "search", "rows": len(found),
                "explanation": "Results:\n" + "\n".join(lines) + "\nOpen one with the read tool."}

    def read(self, url: str) -> Dict[str, Any]:
        asked = str(url).strip().strip("<>\"'")
        address = self.offered.get(asked.replace("http://", "https://", 1).rstrip("/"))
        if address is None:
            known = " , ".join(f["url"] for f in self.results) or "none yet: run search first"
            return {"status": "error", "function_name": "read", "rows": None,
                    "explanation": f"read only opens an address that search returned. The addresses it returned: {known}"}
        try:
            host = urlparse(address).hostname or ""
            reader = (read_paper if host.endswith("arxiv.org") else read_vulnerability if address.startswith(NVD_PAGE)
                      else read_advisory_record if address.startswith(OSV_PAGE) else read_page)
            text, links = reader(address, self._sent)
        except Closed as e:
            return {"status": "error", "function_name": "read", "rows": None,
                    "explanation": f"The page could not be read: {e}. Read another result."}
        except Exception as e:
            return {"status": "error", "function_name": "read", "rows": None,
                    "explanation": f"The page could not be read: {type(e).__name__}: {' '.join(str(e).split())[:300]}"}
        self._offer(links)
        return {"status": "success", "function_name": "read", "rows": len(text), "explanation": text}


if __name__ == "__main__":
    main(ENV_TYPE, EndpointEnvironment)
