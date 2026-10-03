"""Source adapters for Judgment 1.0: validated v4 email facts and typed cards."""
import json
import math
import re
from datetime import date
import fact_parsers as FP
import fact_store as FS
import pipeline_v3 as P
import semantics as SEM

# The party who can establish an operational state. Customer claims are retained
# but cannot establish our receipt, approval, PI dispatch or laboratory result.
AUTHORITY = {
    "product": {"customer", "company"}, "product_code": {"customer", "company"},
    "quantity": {"customer", "company"}, "specification": {"customer", "company"},
    "quantity_qualifier": {"customer", "company"},
    "payment_status": {"company"}, "payment_due": {"company"},
    "payment_checked_at": {"company"}, "pi_sent": {"company"},
    "test_value": {"company", "lab"}, "test_min": {"company"}, "test_max": {"company"},
    "metric": {"company", "lab"}, "unit": {"company", "lab"},
    "price_approved": {"company"}, "delivery_approved": {"company"},
}
MEASUREMENTS = {"test_value", "test_min", "test_max"}
DATES = {"payment_due", "payment_checked_at"}
BOOLS = {"pi_sent", "price_approved", "delivery_approved"}


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected an ISO YYYY-MM-DD date")
    return date.fromisoformat(value)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate card field")
        result[key] = value
    return result


def _card_spans(text):
    """Walk JSON tokens, so strings containing key-like text cannot forge spans."""
    decoder, pos, spans = json.JSONDecoder(), text.index("{") + 1, {}
    while True:
        while text[pos].isspace():
            pos += 1
        if text[pos] == "}":
            return spans
        start = pos
        key, pos = decoder.raw_decode(text, pos)
        while text[pos].isspace():
            pos += 1
        pos += 1  # colon, already checked by json.loads
        while text[pos].isspace():
            pos += 1
        _, pos = decoder.raw_decode(text, pos)
        spans[key] = [start, pos]
        while text[pos].isspace():
            pos += 1
        if text[pos] == ",":
            pos += 1


def _check_value(field, value):
    if field in BOOLS:
        valid = type(value) is bool
    elif field in MEASUREMENTS or field == "quantity":
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
        if field == "quantity":
            valid = valid and value > 0 and int(value) == value
    elif field in DATES:
        iso_date(value)
        valid = True
    else:
        valid = isinstance(value, str) and bool(value.strip()) and len(value) <= 2000
    if field == "payment_status":
        valid = value in ("pending", "received", "failed", "unknown")
    if field == "quantity_qualifier":
        valid = value in ("approx", "min", "max", "exact")
    if not valid:
        raise ValueError("Invalid card value for " + field)


def _card(source, subject):
    text = source["text"]
    card = json.loads(text, object_pairs_hook=_pairs)
    if not isinstance(card, dict) or card.get("subject") != subject:
        raise ValueError("Card subject does not match the judgment subject")
    if set(card) - (set(AUTHORITY) | {"subject"}):
        raise ValueError("Unsupported card fields")
    spans, facts = _card_spans(text), []
    for field, value in card.items():
        if field == "subject":
            continue
        _check_value(field, value)
        admitted = source["party"] in AUTHORITY[field]
        if field in MEASUREMENTS and not all(card.get(x) for x in ("metric", "unit")):
            admitted = False
        start, end = spans[field]
        facts.append({"fact_id": source["id"] + ":" + field, "source_id": source["id"],
                      "field": field, "value": value, "quote": text[start:end], "span": [start, end],
                      "semantic_role": "FACT", "stance": source["party"],
                      "status": "supported" if admitted else "unconfirmed"})
    return facts


def _email(source):
    if source["party"] != "customer":
        raise ValueError("Email adapter accepts inbound customer sources only; use an attested fact card for internal state")
    text = source["text"]
    parsed = FP.collect(text)
    store, _, _ = FS.build(parsed, text, P._demo_selections(parsed))
    facts = []
    for t in SEM.build_typed(text, parsed, store):
        field = {"product": "product", "product_code": "product_code"}.get(t["fact_type"])
        value = t["value"]
        if t["evidence_type"] == "doc_id":
            continue
        if t["evidence_type"] == "qty":
            field = "quantity"
            value = float(t.get("number", "0").replace(",", ""))
            _check_value(field, value)
        if field is None:
            if t["evidence_type"] in ("amount", "incoterm", "payment_terms", "date", "date_bare_month", "date_range"):
                field = t["fact_type"]
            else:
                continue
        base = {"fact_id": source["id"] + ":" + t["id"], "source_id": source["id"],
                "field": field, "value": value, "quote": t["source_span"], "span": t["span"],
                "semantic_role": t["semantic_role"], "stance": t["stance"], "status": t["status"]}
        facts.append(base)
        if field == "quantity" and (t.get("qualifier") or {}).get("kind"):
            start, end = max(0, t["span"][0] - 32), min(len(text), t["span"][1] + 16)
            facts.append(dict(base, fact_id=base["fact_id"] + ":qualifier",
                              field="quantity_qualifier", value=t["qualifier"]["kind"],
                              quote=text[start:end], span=[start, end]))
    return facts


def build(payload):
    if payload.get("scenario") not in ("inquiry", "payment", "sample_test"):
        raise ValueError("Unknown judgment scenario")
    if not isinstance(payload.get("subject"), str) or not payload["subject"].strip():
        raise ValueError("A subject identifier is required")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 20:
        raise ValueError("Provide between 1 and 20 sources")
    if payload.get("as_of") is not None:
        iso_date(payload["as_of"])
    by_id, facts = {}, []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str) or not source["id"]:
            raise ValueError("Each source needs a non-empty string id")
        if source["id"] in by_id:
            raise ValueError("Duplicate source id")
        if source.get("party") not in ("customer", "company", "lab"):
            raise ValueError("Unknown source party")
        if not isinstance(source.get("text"), str) or not source["text"].strip() or len(source["text"]) > 40000:
            raise ValueError("Source text is empty or too long")
        if source.get("format") not in ("email", "fact_card"):
            raise ValueError("Unknown source format")
        by_id[source["id"]] = source
        facts.extend(_card(source, payload["subject"]) if source["format"] == "fact_card" else _email(source))
    return facts, by_id
