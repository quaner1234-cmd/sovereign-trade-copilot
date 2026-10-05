"""Source-backed permissions, independent of customer-language rendering."""
from copy import deepcopy
import hashlib
import json
import re
from .value_store import ValueStore
from .judgment_v2 import _conflicts, _scope_applies
from .understand import COMMERCIAL_TOPICS
CONTRACT_VERSION = "v2-first-reply-1.2"
_TOPIC_MARKERS = COMMERCIAL_TOPICS
def _public_contract(contract):
    return {key: deepcopy(value) for key, value in contract.items() if not key.startswith("_")}

def _topic(key):
    key = str(key).lower()
    if key.startswith("moq"):
        return "moq"
    if "sample" in key and ("price" in key or "cost" in key):
        return "sample_cost"
    if any(part in key for part in ("price", "cost", "amount")):
        return "price"
    if "lead_time" in key:
        return "lead_time"
    if "payment" in key:
        return "payment"
    if "shipping" in key or "transit" in key:
        return "shipping"
    return None


def build_contract(result, registry):
    """Freeze permissions from validated facts; do not derive company truth."""
    understanding, advance = result["understanding"], result["advance"]
    sources = {s["id"]: s for s in registry["sources"]}
    validated = ValueStore(registry).extend(result.get("values", [])).candidates
    lines = [deepcopy(line) for line in understanding.get("lines", []) if line.get("stage") == "current"]
    current_ids = {line["id"] for line in lines}
    unresolved_ids = {cid for selection in result.get("value_selections", [])
                      if selection.get("status") == "unresolved" for cid in selection.get("candidate_ids", [])}
    confirmed_groups = {}
    for candidate in validated:
        if candidate["status"] == "company_confirmed" and candidate.get("active", True) and candidate.get("applicable", True):
            confirmed_groups.setdefault((candidate["key"], candidate["scope"]), []).append(candidate)
    for group in confirmed_groups.values():
        if _conflicts(group):
            unresolved_ids.update(c["id"] for c in group)
    facts, operator_only, allowed_values = [], [], []
    for candidate in validated:
        if candidate["status"] in {"unknown", "rejected"}:
            continue
        source = sources[candidate["source_id"]]
        proof = candidate["provenance"]
        fact = {"id": candidate["id"], "key": candidate["key"], "value": deepcopy(candidate.get("value")),
                "unit": candidate.get("unit"), "scope": candidate["scope"],
                "scope_spec": deepcopy(candidate.get("scope_spec")), "conditions": deepcopy(candidate.get("conditions", [])),
                "line_ids": ([candidate["line_id"]] if candidate.get("line_id") else
                             deepcopy(candidate.get("preferred_line_ids", candidate.get("applicable_line_ids", [])))),
                "purpose": candidate.get("purpose"), "qualifier": candidate.get("qualifier", "exact"),
                "approximate": candidate.get("approximate", False), "status": candidate["status"],
                "source_id": source["id"], "quote": proof["quote"], "span": deepcopy(proof["span"]),
                "evidence_ids": deepcopy(candidate.get("evidence_ids", [])),
                "source": {key: source.get("metadata", {}).get(key) for key in ("url", "publisher", "access_date", "source_date")}}
        if candidate["status"] in {"public_reference", "working_value"} and candidate.get("role") != "external":
            # A readable listing's product identity is usable as that listing's
            # reference; supplier commercial conditions are operator-only.
            listing_fact = source["kind"] == "referenced_url" and candidate["key"] == "product"
            if not listing_fact:
                operator_only.append({**fact, "reason": "Company-specific public/working evidence requires Confirm/Edit before a customer claim.",
                                      "confirmation_point": proof.get("confirmation_point")})
                continue
        if not candidate.get("active", True) or not candidate.get("applicable", True) or not candidate.get("preferred", True):
            continue
        if candidate["id"] in unresolved_ids or candidate.get("resolution") == "unresolved":
            operator_only.append({**fact, "reason": "Unresolved candidates require human adjudication; no customer factual selection."})
            continue
        if candidate.get("line_id") and candidate["line_id"] not in current_ids:
            continue
        if candidate["status"] == "company_confirmed" and not (any(_scope_applies(candidate, line) for line in lines)
                or not lines and _scope_applies(candidate)):
            continue
        role = "company" if candidate["status"] == "company_confirmed" else "customer" if candidate["status"] == "customer_stated" else "system" if candidate["status"] == "system_reported" else "external"
        facts.append({**fact, "role": role})
        allowed_values.append(deepcopy(candidate))
    evidence = []
    for item in result["trust"].get("evidence", []):
        source, span = sources.get(item.get("source_id")), item.get("span", [])
        if source and source["status"] == "read" and len(span) == 2 and source["text"][span[0]:span[1]] == item.get("quote"):
            evidence.append({**deepcopy(item), "role": "customer" if source["party"] == "customer" else "external"})
    asks = deepcopy(understanding.get("customer_asks", []))
    ask_text = " ".join(str(item.get("text", "")) for item in asks)
    obligations = []
    for fact in facts:
        topic = _topic(fact["key"])
        if fact["role"] not in {"company", "external"} or topic is None:
            continue
        explicitly_asked = bool(re.search(_TOPIC_MARKERS[topic], ask_text, re.I))
        current_barrier = fact["role"] == "company" and topic == "moq" and advance["action"] == "ALIGN_MOQ"
        if explicitly_asked or current_barrier:
            obligations.append({"id": "A-" + fact["id"], "key": fact["key"], "candidate_ids": [fact["id"]],
                                "line_ids": fact["line_ids"], "reason": "Answer the already authorized current condition before questions.",
                                "value": deepcopy(fact["value"]), "unit": fact["unit"], "conditions": fact["conditions"]})
    questions = [{"id": "PQ" + str(index + 1), **deepcopy(question)} for index, question in enumerate(advance.get("customer_questions", []))]
    contract = {"schema_version": CONTRACT_VERSION, "language": understanding["customer_language"],
                "judgment": deepcopy(advance), "assessment": deepcopy(result["assessment"]),
                "lines": lines, "customer_asks": asks, "permitted_facts": facts,
                "permitted_evidence": evidence, "answer_obligations": obligations,
                "permitted_questions": questions, "operator_only": operator_only,
                "coverage": deepcopy(registry["coverage"]),
                "source_context": [{"id": source["id"], "kind": source["kind"],
                                    "party": source["party"], "status": source["status"],
                                    "text": source["text"] if source["status"] == "read" else ""}
                                   for source in registry["sources"] if source["party"] == "customer"],
                "boundaries": ["Only scoped, resolved company confirmation grants company factual authority.",
                               "Public/working company-specific values are reviewer-only, even when concrete.",
                               "A next-move statement authorizes reversible work intent only; no execution or commercial acceptance.",
                               "Unread attachment/thread coverage is not absence of customer information."],
                "needs_human_approval": True,
                "_validation": {"registry": deepcopy(registry), "understanding": deepcopy(understanding), "values": allowed_values}}
    contract["contract_hash"] = hashlib.sha256(json.dumps(_public_contract(contract), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return contract
