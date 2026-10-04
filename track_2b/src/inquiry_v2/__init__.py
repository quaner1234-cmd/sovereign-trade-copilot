"""New-inquiry P0-P2 entry point, independent of the frozen v4 field pipeline."""
from copy import deepcopy
from .contract import SCHEMA_VERSION, validate_output
from .source_registry import build
from .value_store import ValueStore
from .understand import understand
from .judgment_v2 import judge
from .guard_v2 import validate_draft
from .research_gate import plan
from .context_runtime import load_context


def analyze(payload, *, context_store=None):
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
    understanding["candidates"] = deepcopy(store.candidates)
    admitted = {c["id"]: c for c in store.candidates if c["status"] not in {"unknown", "rejected"}}
    # Judgment must never consume a rejected quantity via an unvalidated line.
    for line in understanding["lines"]:
        if line.get("selected_quantity_candidate_id") not in admitted:
            line["quantity"] = None
            line["quantity_purpose"] = "unknown"
    context, context_info, private_view = load_context(payload, registry, understanding, context_store)
    store.sources = {source["id"]: source for source in registry["sources"]}
    store.extend(context)
    research = plan(registry, payload.get("research"))
    judgment = judge(understanding, registry, store.candidates, research)
    draft = payload.get("candidate_draft")
    if draft is not None and not isinstance(draft, str):
        raise ValueError("candidate_draft must be a string")
    guard = validate_draft(draft, understanding, registry, store.candidates) if draft is not None else {
        "passed": None, "status": "not_run", "issues": [], "reason": "No draft composed in P0-P2."}
    selections = []
    persisted_ids = {c["id"] for c in (private_view or {}).get("candidates", [])}
    for key, scope in sorted({(c["key"], c["scope"]) for c in store.candidates if c["key"] != "quantity" and c["id"] not in persisted_ids}):
        selections.append({"key": key, "scope": scope, **store.select(key, scope)})
    selections.extend((private_view or {}).get("selections", []))
    return validate_output({
        "schema_version": SCHEMA_VERSION, "understanding": understanding,
        "assessment": judgment["assessment"], "values": store.candidates,
        "value_selections": selections, "advance": judgment["advance"],
        "reply": {"language": understanding["customer_language"], "draft": None, "status": "not_composed"},
        "trust": {"coverage": registry["coverage"], "evidence": understanding["evidence"],
                  "guard": guard, "value_issues": store.issues, "model": model,
                  "research": research, "company_context": context_info, "needs_human_approval": True},
    }, registry)
