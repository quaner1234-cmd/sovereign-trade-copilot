"""Bounded public evidence extraction; snippets and retail quotes are not facts."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import ipaddress
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .understand import PRODUCT_RE, canonical_product

N = r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?"
COUNT = re.compile(rf"(?<![\w.-])(?P<a>{N})(?:\s*[-–—]\s*(?P<b>{N}))?\s*(?:pieces?|pcs|units?)\b", re.I)
MONEY = re.compile(rf"(?P<currency>USD|EUR|GBP|[$€£])\s*(?P<a>{N})(?:\s*[-–—]\s*(?:USD|EUR|GBP|[$€£])?\s*(?P<b>{N}))?(?!\w|\.\d)", re.I)
TIME = re.compile(rf"(?<![\w.-])(?P<a>{N})(?:\s*[-–—]\s*(?P<b>{N}))?\s*(?P<unit>business days?|working days?|calendar days?|days?|weeks?)\b", re.I)
MARKERS = {"moq": r"\bMOQ\b|minimum order|minimum quantity", "price": r"price|wholesale|FOB|per piece",
           "sample_cost": r"sample|prototype|pattern|development", "lead_time": r"production|lead time|manufactur",
           "shipping": r"transit|shipping|transport|delivery", "material": r"material|fabric|construction|polyester|cotton|reflective",
           "compliance": r"PPE|conformity|CE marking|Regulation", "identity": r"registered|registration|company|business"}
CARRIERS = ("dhl.com", "maersk.com", "ups.com", "fedex.com", "cma-cgm.com", "hapag-lloyd.com", "msc.com")
SECONDARY_HOSTS = ("youtube.com", "youtu.be", "reddit.com", "quora.com", "facebook.com", "instagram.com", "tiktok.com", "pinterest.com", "alibaba.com", "amazon.com")
ROUNDUP = re.compile(r"\b(?:top|best)\s+\d+\b[^\n]{0,60}\b(?:manufacturers?|suppliers?|factories)\b|\b(?:manufacturer|supplier)\s+(?:rankings?|reviews?|directory)\b", re.I)


def now_utc():
    return datetime.now(timezone.utc)


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except ValueError:
        return None


def current(candidate, now=None):
    review = candidate.get("provenance", {}).get("review_on")
    return review is None or bool(parse_time(review) and parse_time(review) > (now or now_utc()))


def public_url(value):
    if not isinstance(value, str):
        raise ValueError("public URL required")
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or "." not in host or host.endswith((".local", ".localhost")):
        raise ValueError("only public HTTPS pages may be researched")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP targets are not public research pages")
    # Do not silently fetch a different document by removing its identifier.
    # Tracking and accidental private parameters are disposable; content keys
    # require a provider-specific policy and are deliberately unsupported here.
    disposable = {"email", "name", "token", "key", "session", "ref", "gclid", "fbclid"}
    parameters = parse_qsl(parsed.query, keep_blank_values=True)
    if host == "eur-lex.europa.eu" and re.fullmatch(r"/legal-content/[A-Z]{2}/TXT/?", parsed.path) and len(parameters) == 1 and parameters[0][0] == "uri" and re.fullmatch(r"CELEX:[0-9][A-Z0-9]{5,29}", parameters[0][1]):
        return urlunsplit(("https", host, parsed.path, urlencode(parameters, safe=":"), ""))
    if any(not (key.lower().startswith("utm_") or key.lower() in disposable)
           for key, _ in parameters):
        raise ValueError("query-dependent public pages require an explicit retrieval policy")
    return urlunsplit(("https", host.lower(), parsed.path or "/", "", ""))


def source_type(url, text):
    host = urlsplit(url).hostname
    if any(host == d or host.endswith("." + d) for d in SECONDARY_HOSTS) or ROUNDUP.search(text):
        return "secondary_or_unknown"
    if host == "europa.eu" or host.endswith(".europa.eu"):
        return "regulator"
    if any(host == domain or host.endswith("." + domain) for domain in CARRIERS):
        return "carrier"
    if re.search(r"\b(?:our MOQ|we manufactur\w*|our factory|we produc\w*)\b", text, re.I) or (re.search(r"OEM|cut.and.sew", text, re.I) and re.search(r"services?|manufactur|factory", urlsplit(url).path, re.I)):
        return "supplier_self_report"
    if re.search(r"data sheet|technical specification|material specification", text, re.I):
        return "manufacturer_spec"
    return "secondary_or_unknown"


def ranked_hits(hits, task):
    """Search snippets rank leads only; they never become value evidence."""
    accepted, rejected = [], []
    for hit in hits[:10]:
        if not isinstance(hit, dict):
            rejected.append("invalid_search_hit")
            continue
        try:
            url = public_url(hit.get("url"))
        except ValueError:
            rejected.append("unsupported_public_url")
            continue
        host = urlsplit(url).hostname
        description = str(hit.get("title", "")) + " " + str(hit.get("description", ""))
        if any(host == d or host.endswith("." + d) for d in SECONDARY_HOSTS) or ROUNDUP.search(description):
            rejected.append("secondary_search_lead")
            continue
        role = source_type(url, description)
        if task["topic"] == "compliance" and role != "regulator" or task["topic"] == "shipping" and role != "carrier":
            rejected.append("non_authoritative_external_lead")
            continue
        score = 2 if role in {"regulator", "carrier", "supplier_self_report", "manufacturer_spec"} else 0
        accepted.append((score, {**hit, "url": url}))
    return [hit for _, hit in sorted(accepted, key=lambda pair: -pair[0])], list(dict.fromkeys(rejected))


def make_source(page, task, now=None):
    now = now or now_utc()
    url = public_url(page.get("url"))
    text = page.get("text", page.get("markdown", ""))
    if not isinstance(text, str) or not text.strip() or page.get("status", "read") != "read":
        raise ValueError("retrieved readable page required; search snippets are leads only")
    text = text[:60000]
    host = urlsplit(url).hostname.removeprefix("www.")
    labels = host.split(".")
    issuer = ".".join(labels[-3:] if host.endswith((".co.uk", ".com.au", ".co.jp")) else labels[-2:])
    role = source_type(url, text)
    truncated = bool(page.get("truncated")) or len(page.get("text", page.get("markdown", ""))) > len(text)
    # One retrieved document can support several narrowly scoped tasks. Its
    # scoped evidence packets must have different ids, never overwrite a
    # previous topic/authority annotation of the same immutable text.
    packet_identity = (url, text, now.isoformat(), task["signature"], role, truncated)
    sid = "public-" + hashlib.sha256(repr(packet_identity).encode()).hexdigest()[:24]
    return {"id": sid, "kind": "public_source", "party": "public", "status": "read", "text": text,
            "scope": "research:" + task["signature"],
            "metadata": {"url": url, "publisher": issuer, "access_date": now.isoformat(),
                         "content_sha256": hashlib.sha256(text.encode()).hexdigest(), "publisher_type": role,
                         "research_signature": task["signature"], "topic": task["topic"],
                         "comparable": task["comparable"], "review_on": (now + timedelta(days=task["ttl_days"])).isoformat(),
                         "retrieval": "full_page", "truncated": truncated}}


def clauses(text):
    # Mask URL punctuation for segmentation only; emit the original literal
    # substring so every evidence span remains independently verifiable.
    masked = re.sub(r"https?://[^\s)>\]]+", lambda m: re.sub(r"[.!?]", " ", m.group()), text)
    for m in re.finditer(r"[^\n.!?]+(?:\.(?=\d)[^\n.!?]+)*[.!?]?", masked):
        if m.group().strip():
            yield m.start(), m.end(), text[m.start():m.end()]


def extract(source, task):
    text, topic = source["text"], task["topic"]
    metadata = source["metadata"]
    role = metadata["publisher_type"]
    if role == "secondary_or_unknown":
        return [], ["secondary_or_unverified_source"]
    if topic == "compliance" and role != "regulator" or topic == "shipping" and role != "carrier":
        return [], ["external_authority_not_primary"]
    product = task["comparable"]["product"]
    source_products = {canonical_product(m.group()) for m in PRODUCT_RE.finditer(text)}
    broad_product = False
    if product and topic not in {"shipping", "identity"} and not any(product == p or product.endswith(" " + p) or p.endswith(" " + product) for p in source_products):
        if topic == "compliance" and re.search(r"personal protective equipment|protective clothing|\bPPE\b", text, re.I):
            broad_product = True
        elif re.search(r"garments?|clothing|apparel", text, re.I) and role == "supplier_self_report":
            broad_product = True
        else:
            return [], ["product_scope_not_supported"]
    observations, issues = [], []
    for start, end, quote in clauses(text):
        # A numeric answer immediately under a MOQ heading is still literal
        # evidence. Include the heading in the quote/span rather than inventing
        # a missing label or looking across unrelated paragraphs.
        if topic == "moq" and not re.search(MARKERS[topic], quote, re.I) and COUNT.search(quote):
            preceding = text[max(0, start - 120):start]
            heading = re.search(r"(?:^|\n)([^\n]{1,80})\n\s*$", preceding)
            if heading and re.search(r"\bMOQ\b|minimum\s*(?:order|quantity|&\s*scale)", heading.group(1), re.I):
                start = max(0, start - 120) + heading.start(1)
                quote = text[start:end]
        if not re.search(MARKERS[topic], quote, re.I):
            if not (topic == "moq" and re.search(r"minimum\s*&\s*scale", quote, re.I)):
                continue
        if re.search(r"do not|not confirmed|cannot|unavailable|contact.{0,12}(?:price|quote)|depends|varies", quote, re.I):
            continue
        if task["role"] == "company_specific" and re.search(r"a supplier|for example|suppose|typically|usually|many factories|some factories|industry average", quote, re.I):
            issues.append("illustrative_or_industry_value_not_own_policy")
            continue
        if task["role"] == "company_specific":
            headings = list(re.finditer(r"^#{1,6}\s+[^\n]+", text[max(0, start - 2000):start], re.M))
            local_products = {canonical_product(m.group()) for m in PRODUCT_RE.finditer(quote)}
            if not local_products and headings:
                local_products = {canonical_product(m.group()) for m in PRODUCT_RE.finditer(headings[-1].group())}
            if local_products and not any(product == p or product.endswith(" " + p) or p.endswith(" " + product) for p in local_products):
                issues.append("different_product_policy")
                continue
            if topic == "moq" and re.search(r"per style|each style|per design", quote, re.I) and re.search(r"per colou?r|each colou?r", quote, re.I):
                issues.append("mixed_moq_bases_need_separate_statements")
                continue
        if task["role"] == "company_specific" and re.search(r"stock|blank|print(?:ed|ing)|embroider|retail", quote, re.I):
            issues.append("stock_decoration_not_cut_and_sew")
            continue
        if task["role"] == "company_specific" and not re.search(r"OEM|cut.and.sew|manufactur|factory|production|pattern|development", text, re.I):
            issues.append("production_mode_unverified")
            continue
        pattern = COUNT if topic == "moq" else MONEY if topic in {"price", "sample_cost"} else TIME if topic in {"lead_time", "shipping"} else None
        matches = list(pattern.finditer(quote)) if pattern else [None]
        if pattern is None:
            if "http" in quote and not re.sub(r"\[[^\]]*\]\([^)]*\)", "", quote).strip(" #*-\t"):
                continue
            assertions = {"compliance": r"must|shall|requires?|required|regulated|applies|exemptions include|sets .{0,30}requirements|conformity assessment|provides evidence|are products",
                          "material": r"made of|composed|consists|fabric|material.{0,30}(?:is|must|specification)|construction.{0,30}(?:is|requires)",
                          "identity": r"registered|incorporated|registration number|our company|we are"}
            if not re.search(assertions[topic], quote, re.I) or len(quote.split()) < 6:
                continue
        for match in matches:
            key = task["key"]
            if match:
                low = float(match.group("a").replace(",", ""))
                high = float(match.group("b").replace(",", "")) if match.group("b") else low
                if low <= 0 or high < low:
                    continue
                low = int(low) if low.is_integer() else low
                high = int(high) if high.is_integer() else high
                value = low if low == high else {"min": low, "max": high}
                if topic == "moq":
                    basis = "style" if re.search(r"per style|each style|per design|/style", quote, re.I) else "colour" if re.search(r"per colou?r|each colou?r|/colou?r", quote, re.I) else "unspecified"
                    key = "moq.style" if basis == "style" else "moq.per_colour" if basis == "colour" else "moq.general"
                    unit = "pcs/" + basis if basis != "unspecified" else "pcs"
                elif topic in {"price", "sample_cost"}:
                    if match.group("currency") == "$" and not re.search(r"\bUSD\b", quote):
                        issues.append("currency_unknown")
                        continue
                    currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(match.group("currency"), match.group("currency").upper())
                    if topic == "price" and not re.search(r"per piece|/piece|/pc|each|per unit", quote, re.I):
                        issues.append("price_unit_unknown")
                        continue
                    unit = currency + ("/piece" if topic == "price" else "/development")
                    basis = "FOB" if re.search(r"\bFOB\b", quote) else "EXW" if re.search(r"\bEXW\b", quote) else "price_basis_unspecified"
                    if re.search(r"from|starting|as low|up to", quote, re.I):
                        issues.append("open_price_bound")
                        continue
                else:
                    unit = match.group("unit").lower()
                    unit = re.sub(r"days?$", "days", unit)
                    unit = re.sub(r"weeks?$", "weeks", unit)
                    basis = task["comparable"].get("route") or "production_schedule"
                    if topic == "shipping" and not all(word.lower() in quote.lower() for word in task["comparable"]["route"].split() if word not in {"to"}):
                        issues.append("route_or_mode_not_supported")
                        continue
            else:
                value, unit, basis = quote.strip(), None, task["comparable"].get("route") or topic
            cid = "reference-" + hashlib.sha256((source["id"] + key + str(start) + str(value)).encode()).hexdigest()[:22]
            if match is None:
                # A paragraph is an individual reference statement, not a new
                # value of one singleton company policy. Different paragraphs
                # must not falsely overwrite/conflict with one another.
                key += "." + hashlib.sha256(value.encode()).hexdigest()[:12]
            conditions = [basis]
            conditions += sorted(set(m.group().casefold() for m in re.finditer(r"\b(?:cotton|polyester|nylon|wool|leather|waterproof|reflective)\b", quote, re.I)))
            tiers = re.findall(r"\b(?:for orders? of|at least|over)\s+[\d,]+\s*(?:pieces?|pcs|units?)\b", quote, re.I)
            conditions += ["quantity_tier:" + tier.casefold() for tier in tiers]
            conditions += sorted(set(m.group().casefold() for m in re.finditer(r"\b(?:capsule collections?|smaller runs?|studio level|factory level|domestic orders?|overseas orders?)\b", quote, re.I)))
            spec = deepcopy(task["scope_spec"])
            if task["role"] == "company_specific" and conditions[1:]:
                spec["conditions"] = sorted(set(spec.get("conditions", []) + conditions[1:]))
            observations.append({"id": cid, "key": key, "value": value, "unit": unit, "status": "public_reference",
                                 "source_id": source["id"], "scope": source["scope"], "scope_spec": spec,
                                 "role": task["role"], "conditions": conditions,
                                 "approximate": bool(re.search(r"around|approximately|about|roughly", quote, re.I)),
                                 "provenance": {"quote": quote, "span": [start, end], "derived_from": [],
                                                "publisher": metadata["publisher"], "review_on": metadata["review_on"],
                                                "topic": topic, "comparison_basis": basis, "research_signature": task["signature"],
                                                "product_scope": "general_category" if broad_product else "product_mentioned"}})
    # Same publisher repeating a policy in navigation is one observation.
    unique = {(c["key"], str(c["value"]), c["unit"], tuple(c["conditions"])): c for c in observations}
    return list(unique.values()), list(dict.fromkeys(issues))
