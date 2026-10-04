"""Decision-relevant, privacy-minimized public research planning."""
import hashlib
import json
import re
from urllib.parse import urlsplit
from .judgment_v2 import _scope_applies
from .understand import FUTURE_RE, PRODUCT_RE, canonical_product
from .research_evidence import public_url

TOPICS = {
    "moq": ("moq.style", "OEM cut and sew factory minimum order quantity per style", "company_specific"),
    "price": ("price.bulk", "OEM cut and sew factory wholesale price per piece", "company_specific"),
    "sample_cost": ("cost.development", "OEM pattern development sample cost fee", "company_specific"),
    "lead_time": ("lead_time.bulk", "OEM production lead time", "company_specific"),
    "shipping": ("shipping.transit", "carrier transit time", "external"),
    "material": ("construction.reference", "manufacturer material construction specification", "external"),
    "compliance": ("compliance.relevance", "site:europa.eu protective clothing PPE requirements", "external"),
    "identity": ("buyer.identity.reference", "company official business identity", "external"),
}
COUNTRIES = {"germany": "Germany", "france": "France", "netherlands": "Netherlands", "eu": "EU", "europe": "EU",
             "united kingdom": "United Kingdom", "united states": "United States", "switzerland": "Switzerland",
             "china": "China", "deutschland": "Germany", "alemania": "Germany"}
TTL_DAYS = {"moq": 30, "price": 3, "sample_cost": 7, "lead_time": 7, "shipping": 2,
            "material": 30, "compliance": 1, "identity": 7}


def plan(registry, options=None, understanding=None, values=None, judgment=None):
    options = options or {}
    allowed = {"enabled", "sources", "max_queries", "max_pages", "route", "identity_verification"}
    if not isinstance(options, dict) or set(options) - allowed or type(options.get("enabled", False)) is not bool:
        raise ValueError("invalid research options; raw queries and private text are not accepted")
    budgets = {"max_queries": options.get("max_queries", 2), "max_pages": options.get("max_pages", 3)}
    if any(type(v) is not int or not 1 <= v <= 3 for v in budgets.values()):
        raise ValueError("research budgets must be integers between one and three")
    sources = registry["sources"]
    refs = [s["id"] for s in sources if s["kind"] in {"public_source", "referenced_url"} and s["status"] == "read"]
    pending = [{"source_id": s["id"], "task": "Read the referenced product source before re-asking.",
                "changes_decision": "Current product and specification basis", "status": s["status"]}
               for s in sources if s["kind"] == "referenced_url" and s["status"] != "read"]
    result = {"enabled": options.get("enabled", False), "ran": False, "refs": refs, "pending": pending,
              "tasks": [], "skipped": [], "issues": [], "budgets": budgets, "triggered": False,
              "reason": "No public result would change this reversible step."}
    if understanding is None:
        result["reason"] = "Explicit source coverage only; typed decision context is required for execution."
        return result
    values = values or []
    text = " ".join(s["text"] for s in sources if s["party"] == "customer" and s["status"] == "read")
    current_text = FUTURE_RE.split(text)[0]
    current = [line for line in understanding["lines"] if line.get("stage") == "current"]
    if understanding.get("stage") == "out_of_scope":
        result["reason"] = "Later project stages cannot trigger new-inquiry research."
        return result
    if not current and any(s["kind"] == "attachment" and s["status"] != "read" for s in sources):
        result["reason"] = "Read the existing brief before deciding what public research is missing."
        return result

    def task(topic, line=None, *, route=None, target=None, basis=None):
        key, terms, role = TOPICS[topic]
        if topic == "moq" and basis == "colour":
            key, terms = "moq.per_colour", terms.replace("per style", "per colour")
        moq_aliases = {"moq.per_colour"} if basis == "colour" else {"moq.style"} if basis == "style" else {"moq.style", "moq.general"}
        aliases = {"moq": moq_aliases, "price": {"price", "price.bulk", "bulk_price"},
                   "sample_cost": {"cost.development", "sample_price"}, "lead_time": {"lead_time.normal", "lead_time.bulk", "lead_time.bulk.default"}}
        confirmed = [c for c in values if c.get("status") == "company_confirmed" and c.get("key") in aliases.get(topic, {key})
                     and _scope_applies(c, line)]
        if role == "company_specific" and confirmed:
            result["skipped"].append({"topic": topic, "line_id": line.get("id") if line else None,
                                      "reason": "Existing company policy or its unresolved conflict needs internal use/adjudication, not a public substitute."})
            return
        original_product = line["product_ref"] if line else ""
        nouns = list(PRODUCT_RE.finditer(original_product))
        product = canonical_product(max(nouns, key=lambda m: len(m.group())).group()) if nouns else ""
        if line and not product:
            result["pending"].append({"topic": topic, "status": "unknown", "reason": "No privacy-safe product taxonomy term; raw product names cannot be sent to research."})
            return
        query = " ".join(p for p in (product, terms, route or "", target or "") if p)
        if topic == "moq":
            # Lead with production mode, keeping stock/logo decoration out of
            # the primary intent while retaining the same narrow product/basis.
            query = "OEM cut and sew " + product + " factory minimum order quantity per " + ("colour" if basis == "colour" else "style")
        spec = {"product_categories": [original_product]} if original_product else {"global": True}
        comparable = {"product": product, "topic": topic, "route": route, "target": target,
                      "production_mode": "cut_and_sew" if role == "company_specific" else None, "requested_basis": basis}
        signature = hashlib.sha256(json.dumps(comparable, sort_keys=True).encode()).hexdigest()
        if role == "external":
            spec = {**({"product_categories": [original_product]} if original_product else {}), "conditions": ["research:" + signature]}
        if any(t["signature"] == signature for t in result["tasks"]):
            return
        result["tasks"].append({"topic": topic, "key": key, "query": query, "signature": signature,
                                "line_id": line.get("id") if line else None, "scope_spec": spec,
                                "role": role, "comparable": comparable, "ttl_days": TTL_DAYS[topic],
                                "changes_decision": "Narrow the current internal " + topic + " review or reference content; company authorization stays Unknown." if role == "company_specific" else
                                                    "Resolve the current external " + topic + " evidence gap before the dependent review."})

    for line in current:
        by_id = {s["id"]: s for s in sources}
        source = by_id[line["source_id"]]["text"]
        start, end = line["span"]
        left = max(source.rfind(mark, 0, start) for mark in ".!?\n") + 1
        positions = [source.find(mark, end) for mark in ".!?\n"]
        right = min((p for p in positions if p >= 0), default=len(source))
        asks = " ".join(str(a.get("text", "")) for a in understanding.get("customer_asks", []) if a.get("stage") != "future")
        relevant = source[left:right] + " " + asks
        if re.search(r"\bMOQ\b|minimum order|起订", relevant, re.I) or (re.search(r"launch", current_text, re.I) and re.search(r"quot|pric|cost", relevant, re.I)):
            if line.get("quantity_purpose") not in {"prototype", "evaluation_sample"}:
                basis = "colour" if re.search(r"per colou?r|each colou?r", relevant, re.I) else "style" if re.search(r"per style|each style", relevant, re.I) else None
                task("moq", line, basis=basis)
        if re.search(r"(?:sample|prototype|pattern).{0,35}(?:cost|quote|fee|budget)|(?:quote|cost).{0,35}(?:sample|prototype|pattern)", relevant, re.I):
            task("sample_cost", line)
        if re.search(r"\b(?:price|pricing|costing|factory quote|production quote|precio)\b|报价|价格", relevant, re.I) and line.get("quantity_purpose") != "prototype":
            task("price", line)
        if re.search(r"lead\s*time|production.{0,25}(?:days|weeks|schedule)|交期", relevant, re.I):
            task("lead_time", line)
        if re.search(r"licensed|reflective|unfamiliar|new industry|material (?:options|specification)|construction (?:options|reference)", relevant, re.I) or (judgment or {}).get("assessment", {}).get("company_fit", {}).get("status") == "needs_internal_review":
            task("material", line)
        market = next((canonical for word, canonical in COUNTRIES.items() if re.search(r"\b" + re.escape(word) + r"\b", text, re.I)), None)
        if market and re.search(r"\b(?:PPE|protective|compliance|regulat\w*|CE marking)\b", relevant, re.I):
            if market in {"EU", "Germany", "France", "Netherlands"}:
                task("compliance", line, route=market)
            else:
                result["pending"].append({"topic": "compliance", "status": "unknown", "reason": "No supported primary regulator scope for this market."})
        if re.search(r"shipping|transport|transit|delivery to|运输", relevant, re.I) and not re.search(r"own forwarder|arrange collection", text, re.I):
            route = options.get("route")
            if isinstance(route, dict) and set(route) == {"origin", "destination", "mode"} and all(isinstance(route[k], str) and route[k].casefold() in COUNTRIES for k in ("origin", "destination")) and isinstance(route["mode"], str) and route["mode"] in {"sea", "air", "express"}:
                route_text = " ".join([COUNTRIES[route["origin"].casefold()], "to", COUNTRIES[route["destination"].casefold()], route["mode"]])
                task("shipping", line, route=route_text)
            else:
                result["pending"].append({"topic": "shipping", "status": "unknown", "reason": "Origin, destination and mode are required before a relevant transit reference."})
    identity = options.get("identity_verification")
    if identity is not None:
        if not isinstance(identity, dict) or set(identity) != {"domain", "changes_decision"} or not isinstance(identity["changes_decision"], str) or not identity["changes_decision"].strip():
            raise ValueError("identity verification requires explicit target and decision consequence")
        domain = identity["domain"]
        if not isinstance(domain, str) or not re.fullmatch(r"[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+", domain) or urlsplit("https://" + domain).hostname != domain.lower():
            raise ValueError("identity target must be a public domain, never an email or private text")
        public_url("https://" + domain)
        task("identity", target="site:" + domain.lower())
        result["tasks"][-1]["changes_decision"] = identity["changes_decision"]
    if result["tasks"]:
        result["reason"] = "Public references can change a named review/working value; company commitments remain subject to Confirm/Edit."
    result["triggered"] = bool(result["tasks"])
    return result
