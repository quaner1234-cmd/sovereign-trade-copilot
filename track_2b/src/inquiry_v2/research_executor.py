"""Optional bounded public research; provider failures cannot block judgment."""
from copy import deepcopy
from datetime import timedelta
import json
import os
import socket
import time
import urllib.error
import urllib.request
from .research_evidence import (extract, make_source, now_utc, parse_time, public_url, ranked_hits)
from .research_synthesis import synthesize
from .value_store import ValueStore


class FirecrawlProvider:
    """Stdlib adapter to the installed provider's documented v2 API."""
    def __init__(self, api_key, *, timeout=12):
        self._key = api_key
        self.timeout = timeout

    def _post(self, endpoint, data):
        request = urllib.request.Request("https://api.firecrawl.dev/v2/" + endpoint,
                    data=json.dumps(data).encode(), headers={"Authorization": "Bearer " + self._key,
                    "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout + 2) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("provider response exceeds budget")
            result = json.loads(raw)
            if not isinstance(result, dict) or result.get("success") is not True:
                raise ValueError("provider returned no successful result")
            return result.get("data", {})
        except (OSError, ValueError, urllib.error.URLError) as error:
            # Never echo request headers, key, remote error bodies or URLs.
            raise OSError("public research provider unavailable") from None

    def search(self, task, limit=10):
        data = self._post("search", {"query": task["query"], "sources": ["web"], "limit": limit,
                                   "timeout": self.timeout * 1000, "domainTools": False})
        return data.get("web", []) if isinstance(data, dict) else []

    def fetch(self, hit):
        url = public_url(hit.get("url"))
        data = self._post("scrape", {"url": url, "formats": ["markdown"], "onlyMainContent": True,
                                   "timeout": self.timeout * 1000, "maxAge": 0})
        if not isinstance(data, dict):
            raise ValueError("unreadable page")
        return {"url": url, "text": data.get("markdown", ""), "status": "read"}


def configured_provider():
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    return FirecrawlProvider(key) if key else None


def execute(plan, *, provider=None, context_store=None, provided_sources=(), now=None):
    result = deepcopy(plan)
    result.update(results=[], cache_hits=0, queries_run=0, pages_read=0, network_attempted=False,
                  source_model="primary full-page evidence with literal quote/span and retrieval date")
    generated_sources, generated_candidates = [], []
    now = now or now_utc()
    if not result["enabled"]:
        result["execution_status"] = "disabled"
        return result, [], []
    if not result["tasks"]:
        result["execution_status"] = "skipped"
        return result, [], []
    # The provider sees task queries and discovered public URLs, never inquiry text.
    provider = configured_provider() if provider is None else provider
    history = context_store.view() if context_store else {"sources": [], "candidates": []}
    all_cached = history["sources"]
    query_budget, page_budget = result["budgets"]["max_queries"], result["budgets"]["max_pages"]
    started = time.monotonic()
    for task in result["tasks"]:
        pages = [s for s in all_cached if s.get("kind") == "public_source" and s.get("status") == "read"
                 and s.get("metadata", {}).get("research_signature") == task["signature"]
                 and (parse_time(s["metadata"].get("review_on")) or now - timedelta(seconds=1)) > now
                 and s["metadata"].get("retrieval") == "full_page"
                 and s["metadata"].get("publisher_type") != "secondary_or_unknown"]
        if not pages:
            for supplied in provided_sources:
                metadata = supplied.get("metadata", {})
                date = parse_time(metadata.get("access_date"))
                if supplied.get("kind") != "public_source" or supplied.get("status") != "read" or metadata.get("retrieval") != "full_page" or not date or date > now or date + timedelta(days=task["ttl_days"]) <= now:
                    continue
                try:
                    source = make_source({"url": metadata.get("url"), "text": supplied["text"], "truncated": metadata.get("truncated", False)}, task, date)
                    if extract(source, task)[0]:
                        pages.append(source)
                        generated_sources.append(source)
                except ValueError:
                    continue
        cached = bool(pages)
        if cached:
            result["cache_hits"] += 1
        elif provider is None:
            result["issues"].append("network_capability_unconfigured:" + task["topic"])
        elif result["queries_run"] >= query_budget or result["pages_read"] >= page_budget or time.monotonic() - started > 50:
            result["issues"].append("research_budget_exhausted:" + task["topic"])
        else:
            result["network_attempted"] = True
            result["queries_run"] += 1
            try:
                hits = provider.search(deepcopy(task), limit=10)
                if not isinstance(hits, list):
                    raise ValueError("invalid search result")
                hits, rejections = ranked_hits(hits, task)
                result["issues"].extend(reason + ":" + task["topic"] for reason in rejections)
                seen = set()
                for hit in hits:
                    if result["pages_read"] >= page_budget or time.monotonic() - started > 50:
                        break
                    try:
                        url = public_url(hit.get("url"))
                        if url in seen:
                            continue
                        seen.add(url)
                        result["pages_read"] += 1
                        source = make_source(provider.fetch({**hit, "url": url}), task, now)
                        pages.append(source)
                        generated_sources.append(source)
                    except (ValueError, OSError, TimeoutError, socket.timeout):
                        result["issues"].append("page_unavailable_or_invalid:" + task["topic"])
            except (ValueError, OSError, TimeoutError, socket.timeout):
                result["issues"].append("network_unavailable:" + task["topic"])
        # A retained source id appears once even if two historic cache packets overlap.
        pages = list({s["id"]: s for s in pages}.values())
        observations, evidence_issues = [], []
        for source in pages:
            candidates, issues = extract(source, task)
            for candidate in candidates:
                try:
                    admitted = ValueStore({"sources": [source]}).add(candidate)
                    if admitted["status"] == "public_reference":
                        observations.append(admitted)
                    else:
                        issues.extend(admitted["rejection_reasons"])
                except ValueError:
                    issues.append("invalid_public_value_shape")
            evidence_issues.extend(issues)
        summary, working_sources, working_candidates = synthesize(task, observations, pages, now)
        summary.update(cache_hit=cached, evidence_issues=list(dict.fromkeys(evidence_issues)))
        # Existing cached synthesis is immutable; use it until expiry rather than
        # appending a new equally-ranked assumption on every repeated inquiry.
        cached_working = [c for c in history["candidates"] if c.get("status") == "working_value" and c.get("active", True)
                          and c.get("provenance", {}).get("research_signature") == task["signature"]
                          and (parse_time(c["provenance"].get("review_on")) or now - timedelta(seconds=1)) > now]
        if cached and len(cached_working) == 1 and (summary.get("recommended_working_value") or {}).get("value") == cached_working[0]["value"]:
            working_sources, working_candidates = [], []
            summary["working_candidate_id"] = cached_working[0]["id"]
        result["results"].append(summary)
        generated_sources.extend(working_sources)
        generated_candidates.extend(observations + working_candidates)
    # Keep references from cache available to downstream source validation.
    referenced = {c["source_id"] for c in generated_candidates}
    generated_sources.extend(s for s in all_cached if s["id"] in referenced)
    generated_sources = list({s["id"]: s for s in generated_sources}.values())
    generated_candidates = list({c["id"]: c for c in generated_candidates}.values())
    result["ran"] = result["network_attempted"]
    result["execution_status"] = "completed" if any(s["status"] != "unknown" for s in result["results"]) else "unavailable_or_unknown"
    result["refs"] = list(dict.fromkeys(result["refs"] + [s["id"] for s in generated_sources if s["party"] == "public"]))
    return result, generated_sources, generated_candidates
