"""Typed inquiry judgment with optional private context and public research."""
from copy import deepcopy
from .contract import SCHEMA_VERSION, validate_output
from .source_registry import build
from .value_store import ValueStore
from .understand import understand
from .judgment_v2 import judge
from .guard_v2 import validate_draft
from .research_gate import plan
from .context_runtime import load_context
from .research_executor import execute


def analyze(payload, *, context_store=None, research_provider=None):
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
    baseline = plan(registry, payload.get("research"))
    judgment = judge(understanding, registry, store.candidates, baseline)
    research = plan(registry, payload.get("research"), understanding, store.candidates, judgment)
    research, research_sources, research_candidates = execute(research, provider=research_provider, context_store=context_store,
        provided_sources=registry["sources"])
    if research_sources:
        existing_sources = {source["id"]: source for source in registry["sources"]}
        for source in research_sources:
            if source["id"] in existing_sources and source != existing_sources[source["id"]]:
                raise ValueError("research source cannot overwrite existing evidence")
            existing_sources[source["id"]] = source
        registry["sources"] = list(existing_sources.values())
        if context_store and (any(c["id"] not in {v["id"] for v in store.candidates} for c in research_candidates) or
                              any(s["id"] not in store.sources for s in research_sources)):
            context_store.record({"sources": research_sources, "candidates": research_candidates}, authority="reference")
        enriched = deepcopy(payload)
        enriched["persist_references"] = False
        enriched["company_context"] = deepcopy(payload.get("company_context") or {})
        enriched["company_context"]["candidates"] = (payload.get("company_context") or {}).get("candidates", []) + research_candidates
        context, context_info, private_view = load_context(enriched, registry, understanding, context_store,
            research_signatures=[task["signature"] for task in research["tasks"]])
        store = ValueStore(registry).extend(understanding["candidates"]).extend(context)
        registry["coverage"]["research"] = {"status": "read", "source_ids": research["refs"]}
        for candidate in research_candidates:
            if candidate["status"] == "public_reference":
                proof = candidate["provenance"]
                understanding["evidence"].append({"id": "R-" + candidate["id"], "source_id": candidate["source_id"],
                    "span": proof["span"], "quote": proof["quote"], "claim": candidate["key"], "scope": candidate["scope"]})
        judgment = judge(understanding, registry, store.candidates, research)
    for reference in research.get("results", []):
        ident = reference.get("working_candidate_id")
        current = next((c for c in store.candidates if c["id"] == ident and c.get("preferred", True) and c.get("applicable", True)
                        and c.get("status") == "working_value" and c.get("resolution") != "unresolved"), None)
        if current:
            judgment["advance"]["value_candidate_ids"].append(ident)
            judgment["advance"]["working_assumptions"].append({"key": current["key"], "value": current["value"],
                "unit": current["unit"], "scope": current["scope"], "owner": current["provenance"]["owner"],
                "scope_spec": current["scope_spec"], "conditions": current["conditions"],
                "confirmation_point": current["provenance"]["confirmation_point"],
                "basis": reference["recommendation_basis"], "confidence": reference["confidence"], "limitations": reference["limitations"],
                "evidence_ids": ["R-" + c["id"] for c in research_candidates if c["status"] == "public_reference" and
                                 c["provenance"].get("research_signature") == reference["signature"]]})
    judgment["advance"]["value_candidate_ids"] = list(dict.fromkeys(judgment["advance"]["value_candidate_ids"]))
    draft = payload.get("candidate_draft")
    if draft is not None and not isinstance(draft, str):
        raise ValueError("candidate_draft must be a string")
    guard = validate_draft(draft, understanding, registry, store.candidates) if draft is not None else {
        "passed": None, "status": "not_run", "issues": [], "reason": "First-reply generation is not enabled."}
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
