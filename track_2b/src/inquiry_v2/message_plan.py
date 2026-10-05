"""Construct an immutable semantic message plan; never compose customer prose."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from .reply_contract import build_contract, _public_contract
from .understand import _sentence_bounds

VERSION = "v2-message-plan-1.0"

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

@dataclass(frozen=True)
class MessagePlan:
    """Nested state is serialized. Every exposed view is a detached copy."""
    document_json: str
    evidence_json: str

    @property
    def document(self):
        return json.loads(self.document_json)

    @property
    def evidence_contract(self):
        return json.loads(self.evidence_json)

    @property
    def hash(self):
        return hashlib.sha256((self.document_json + self.evidence_json).encode()).hexdigest()

    def public(self):
        return {**self.document, "plan_hash": self.hash}

def _links(fact, sources):
    source = sources[fact["source_id"]]
    return {"source": {"id": source["id"], "span": fact["span"], "quote": fact["quote"]},
            "judgment": None, "authorization": ({"source_id": source["id"], "scope": fact["scope"],
                "confirmed_by": source.get("metadata", {}).get("confirmed_by"),
                "confirmed_at": source.get("metadata", {}).get("confirmed_at")}
                if fact["role"] == "company" else {"kind": fact["status"]})}

def _source_conditions(fact, source):
    # Retain literal, source-local applicability that an older candidate omitted.
    # Do not generalize this clause or write it back into the company ledger.
    left, right = _sentence_bounds(source["text"], *fact["span"])
    sentence = source["text"][left:right]
    clauses = [m.group().strip(" .。") for m in re.finditer(
        r"\b(?:for|subject\s+to|provided\s+that|only\s+if|when|after)\s+[^.;。]+|(?:适用于|仅限|在).{1,70}(?:条件下|路线|材料)", sentence, re.I)]
    return list(dict.fromkeys(fact.get("conditions", []) + clauses))

def build(result, registry):
    contract = build_contract(result, registry)
    sources = {s["id"]: s for s in registry["sources"]}
    facts = deepcopy(contract["permitted_facts"])
    for fact in facts:
        fact["provenance"] = _links(fact, sources)
        if fact["role"] in {"company", "external"}:
            fact["conditions"] = _source_conditions(fact, sources[fact["source_id"]])
        fact['basis']={'unit':fact['unit'],'scope':fact['scope'],'conditions':deepcopy(fact['conditions'])}
    by_id = {fact["id"]: fact for fact in facts}
    contract["permitted_facts"] = deepcopy(facts)
    issues = []
    lines = deepcopy(contract["lines"])
    line_ids = {line["id"] for line in lines}
    evidence = {e["id"]: e for e in contract["permitted_evidence"]}
    advance = contract["judgment"]
    primary = deepcopy(advance["primary_advance"])
    if (primary.get("action") != advance["action"] or primary.get("execution_authorized") is not False
            or primary.get("external_commitment") is not False or primary.get("reversible") is not True):
        issues.append("upstream_invalid_approved_advance")
    if any(str(i).startswith(("line_quantity_conflict:", "invalid_quantity_range:")) for i in result["understanding"].get("issues", [])):
        issues.append("upstream_unresolved_quantity")
    if result["understanding"].get("stage") == "out_of_scope":
        issues.append("upstream_out_of_first_reply_scope")

    def action_item(item, ident):
        dependencies = item.get("source_preconditions", [])
        checks = {c["field"] for c in advance.get("internal_checks", [])}
        action = item["action"]
        if dependencies:
            operation = "inspect existing referenced material before dependent decisions"
        elif action == "INTERNAL_VERIFICATION" and "licensed_sourcing" in checks:
            operation = "verify material sourcing rights and technical feasibility"
        elif action == "INTERNAL_COSTING":
            operation = "review preliminary development cost and construction" if advance.get("costing_scope") == "development" else "review preliminary construction cost basis"
        else:
            operation = {"ALIGN_MOQ": "review minimum quantity alignment and a possible small-run route",
                "VERIFY_SAMPLE_ROUTE": "check evaluation sample route, availability and cost",
                "ASSESS_COMPANY_FIT": "review current product fit and feasible development route",
                "INTERNAL_VERIFICATION": "verify current product route and applicable company conditions",
                "REQUEST_INFORMATION": "use the approved answers to review preliminary costing or development route",
                "RESEARCH": "inspect the existing product reference before deciding the next route",
                "OUT_OF_SCOPE": "refer the existing project to its responsible owner"}.get(action)
        # Preserve approved task meaning; action enums alone are not a plan.
        # The fallback is only for older judgments lacking a structured task.
        operation = item.get("task") or operation
        refs = item.get("evidence_ids", [])
        if not set(refs) <= evidence.keys():
            issues.append("upstream_unknown_judgment_evidence")
        return {"id": ident, "kind": "advance", "action": action, "operation": operation,
            "line_ids": deepcopy(item.get("line_ids", sorted(line_ids))), "conditions": deepcopy(item.get("conditions", [])),
            "source_preconditions": deepcopy(dependencies), "reversible": True,
            "external_commitment": False, "execution_authorized": False,
            "provenance": {"judgment": {"path": "advance." + ("primary_advance" if ident == "primary" else "parallel_reversible_advances"), "id": item.get("id"), "action": action},
                "source": [deepcopy(evidence[r]) for r in refs] + [{"source_id": d["source_id"], "state": d["state"]} for d in dependencies],
                "authorization": {"kind": "approved_reversible_work_intent", "execution_authorized": False}}}

    primary = action_item(primary, "primary")
    parallel = [action_item(item, "parallel-" + str(index + 1)) for index, item in enumerate(advance.get("parallel_reversible_advances", []))]
    answers = []
    for old in contract["answer_obligations"]:
        linked = [by_id[i] for i in old["candidate_ids"]]
        answers.append({"id": old["id"], "kind": "answer", "topic": old["key"], "line_ids": old["line_ids"],
            "facts": deepcopy(linked), "conditions": list(dict.fromkeys(c for f in linked for c in f["conditions"])),
            "provenance": {"source": [f["provenance"]["source"] for f in linked],
                "authorization": [f["provenance"]["authorization"] for f in linked],
                "judgment": {"path": "understanding.customer_asks", "reason": old["reason"]}}})
    questions = []
    forbidden_questions = [{"field": "quantity", "line_id": fact["line_ids"][0] if fact["line_ids"] else None,
        "reason": "already supplied", "provenance": fact["provenance"]} for fact in facts if fact["key"] == "quantity" and fact["role"] == "customer"]
    forbidden_questions.append({'field':'any unapproved decision variable','reason':'Only approved decision-changing questions may be rendered.',
        'provenance':{'judgment':'advance.customer_questions'}})
    for question in contract["permitted_questions"]:
        if question.get("field") == "quantity" and any(q['field']=='quantity' and q.get("line_id") == question.get("line_id") for q in forbidden_questions):
            issues.append("upstream_judgment_reasks_known_quantity")
        if primary["source_preconditions"]:
            issues.append("upstream_question_before_existing_source_review")
        questions.append({"id": question["id"], "kind": "question", "field": question["field"],
            "line_ids": [question["line_id"]] if question.get("line_id") else [],
            "question": question.get("question", question.get("text")),
            "provenance": {"source": [deepcopy(evidence[r]) for r in question.get("evidence_ids", []) if r in evidence],
                "judgment": {"path": "advance.customer_questions", "changes_decision": question["changes_decision"],
                    "no_re_ask_basis": question["no_re_ask_basis"]}, "authorization": {"kind": "approved_customer_question"}}})
    polarity = [{"line_id": line["id"], "text": cue["text"], "polarity": cue.get("polarity", "positive"),
        "provenance": {"source_id": cue["source_id"], "span": cue["span"], "quote": cue["text"]}}
        for line in lines for cue in line.get("spec_cues", [])]
    states = [{"source_id": s["id"], "kind": s["kind"], "state": s["status"],
        "line_id": s.get("metadata", {}).get("line_id"), "provenance": {"source_id": s["id"], "state": s["status"]}}
        for s in registry["sources"] if s["kind"] in {"attachment", "referenced_url", "thread_message"}]
    ownership = [{"candidate_id": f["id"], "value": f["value"], "unit": f["unit"], "line_ids": f["line_ids"],
        "purpose": f["purpose"], "qualifier": f["qualifier"], "provenance": f["provenance"]} for f in facts if f["key"] == "quantity"]
    forbidden = [{"claim": "execution or commercial acceptance", "provenance": {"judgment": "advance.commitment_boundaries"}},
        {"claim": "interest or inquiry becomes confirmed order", "provenance": {"source": "understanding.stage"}},
        {"claim": "public or working company terms become company truth", "provenance": {"authorization": "company_confirmed only"}},
        {"claim": "unread content becomes reviewed or absent", "provenance": {"source": states}},
        {"claim": "unsupported company capability, stock, certification, quotation or payment acceptance", "provenance": {"authorization": [f["provenance"] for f in facts if f["role"] == "company"]}}]
    slots = [{"id": "answer-"+str(i+1), "item_ids": [a["id"]], "required": True} for i,a in enumerate(answers)]
    slots += [{"id": "primary", "item_ids": ["primary"], "required": True}]
    slots += [{"id": p["id"], "item_ids": [p["id"]], "required": False} for p in parallel]
    slots += [{"id": q["id"], "item_ids": [q["id"]], "required": True} for q in questions]
    doc = {"schema_version": VERSION, "language": contract["language"], "line_item_scope": lines,
        "required_answers": answers, "approved_questions": questions, "forbidden_questions": forbidden_questions,
        "primary_advance": primary, "parallel_reversible_advances": parallel,
        "allowed_customer_facts": [f for f in facts if f["role"] in {"customer", "system"}],
        "allowed_company_claims": [f for f in facts if f["role"] == "company"],
        "allowed_external_references": [f for f in facts if f["role"] == "external"],
        "forbidden_claims": forbidden, "polarity_constraints": polarity, "quantity_ownership": ownership,
        "source_state": states, "source_coverage":deepcopy(contract['coverage']), "ordered_message_slots": slots, "needs_human_approval": True,
        "construction_issues": list(dict.fromkeys(issues))}
    return MessagePlan(encode(doc), encode(contract))

def customer_view(plan):
    """Keep IDs for content binding, not full provenance, owners or raw sources."""
    doc = plan.document
    def clean_fact(f):
        return {k: deepcopy(f[k]) for k in ("key", "value", "unit", "scope", "scope_spec", "line_ids", "conditions", "purpose", "qualifier", "role")}
    items = [{"id": a["id"], "kind": "answer", "facts": [clean_fact(f) for f in a["facts"]]} for a in doc["required_answers"]]
    for item in [doc["primary_advance"]] + doc["parallel_reversible_advances"]:
        items.append({"id": item["id"], "kind": "advance", "operation": item["operation"], "line_ids": item["line_ids"],
            "conditions": item["conditions"], "existing_sources_to_inspect": bool(item["source_preconditions"])})
    items += [{k: q[k] for k in ("id", "kind", "field", "line_ids", "question")} for q in doc["approved_questions"]]
    return {"language": doc["language"], "items": items,
        "required_item_ids": [s["item_ids"][0] for s in doc["ordered_message_slots"] if s["required"]],
        "products": [{"line_id": l["id"], "product": l["product_ref"], "quantity": l.get("quantity"),
            "quantity_purpose": l.get("quantity_purpose")} for l in doc["line_item_scope"]],
        "optional_customer_facts": [clean_fact(f) for f in doc["allowed_customer_facts"] if f["key"] == "quantity"],
        "polarity_constraints": [{k:p[k] for k in ("line_id", "text", "polarity")} for p in doc["polarity_constraints"]],
        "existing_source_states": [{"kind": s["kind"], "state": s["state"]} for s in doc["source_state"]],
        "boundaries": ["Only express supplied content; no new fact or customer question.",
            "Work intent is verification or preliminary review, never a firm quote or execution.",
            "Interest is not an order; unread material is existing material to inspect."]}
