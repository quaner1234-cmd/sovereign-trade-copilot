"""New-inquiry P0-P2 entry point, independent of the frozen v4 field pipeline."""
from copy import deepcopy
from .contract import SCHEMA_VERSION, validate_output
from .source_registry import build
from .value_store import ValueStore
from .understand import understand
from .judgment_v2 import judge
from .guard_v2 import validate_draft
from .research_gate import plan


def analyze(payload):
    registry = build(payload)
    if type(payload.get("use_model", False)) is not bool:
        raise ValueError("use_model must be boolean")
    proposals = payload.get("model_proposals")
    if proposals is not None and (not isinstance(proposals, dict) or not isinstance(proposals.get("candidates"), list)):
        raise ValueError("model_proposals requires candidates array")
    model = {"status": "not_run", "reason": "Offline typed extraction; no model call requested."}
    if payload.get("use_model"):
        from .model_proposals import propose
        proposals, model = propose(registry)
    understanding = understand(registry, proposals)
    store = ValueStore(registry).extend(understanding["candidates"])
    context = payload.get("company_context") or {}
    store.extend(context.get("candidates", []))
    understanding["candidates"] = deepcopy(store.candidates[:len(understanding["candidates"])])
    admitted = {c["id"]: c for c in store.candidates if c["status"] not in {"unknown", "rejected"}}
    # Judgment must never consume a rejected quantity via an unvalidated line.
    for line in understanding["lines"]:
        if line.get("selected_quantity_candidate_id") not in admitted:
            line["quantity"] = None
            line["quantity_purpose"] = "unknown"
    research = plan(registry, payload.get("research"))
    judgment = judge(understanding, registry, store.candidates, research)
    draft = payload.get("candidate_draft")
    if draft is not None and not isinstance(draft, str):
        raise ValueError("candidate_draft must be a string")
    guard = validate_draft(draft, understanding, registry, store.candidates) if draft is not None else {
        "passed": None, "status": "not_run", "issues": [], "reason": "No draft composed in P0-P2."}
    selections = []
    for key, scope in sorted({(c["key"], c["scope"]) for c in store.candidates if c["key"] != "quantity"}):
        selections.append({"key": key, "scope": scope, **store.select(key, scope)})
    return validate_output({
        "schema_version": SCHEMA_VERSION, "understanding": understanding,
        "assessment": judgment["assessment"], "values": store.candidates,
        "value_selections": selections, "advance": judgment["advance"],
        "reply": {"language": understanding["customer_language"], "draft": None, "status": "not_composed"},
        "trust": {"coverage": registry["coverage"], "evidence": understanding["evidence"],
                  "guard": guard, "value_issues": store.issues, "model": model,
                  "research": research, "needs_human_approval": True},
    }, registry)
