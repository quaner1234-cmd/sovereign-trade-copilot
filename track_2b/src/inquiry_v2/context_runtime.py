"""Load scoped private evidence after understanding; never learn from email facts."""
from copy import deepcopy
from .private_context import project_context
from .value_store import ValueStore


def request_context(payload, understanding):
    supplied = payload.get("request_context", {})
    if not isinstance(supplied, dict) or set(supplied) - {"project_id", "markets", "conditions"}:
        raise ValueError("request_context permits explicit project_id, markets and conditions")
    for name in ("markets", "conditions"):
        if name in supplied and (not isinstance(supplied[name], list) or any(not isinstance(v, str) or not v.strip() for v in supplied[name])):
            raise ValueError(name + " requires operator context strings")
    if "project_id" in supplied and (not isinstance(supplied["project_id"], str) or not supplied["project_id"].strip()):
        raise ValueError("project_id requires operator context identity")
    context = deepcopy(supplied)
    context["lines"] = []
    candidates = {c["id"]: c for c in understanding["candidates"]}
    for line in understanding["lines"]:
        if line.get("stage") != "current":
            continue
        quantity, qualifier = line.get("quantity"), line.get("quantity_qualifier")
        quantity_fact = candidates.get(line.get("selected_quantity_candidate_id"), {})
        if qualifier == "approximate" or quantity_fact.get("approximate"):
            quantity = None
        elif qualifier == "minimum":
            quantity = {"min": quantity}
        elif qualifier == "maximum":
            quantity = {"min": 0, "max": quantity}
        context["lines"].append({"id": line["id"], "product_categories": [line["product_ref"]],
                                 "quantity": quantity, "quantity_unit": "pcs"})
    return context


def load_context(payload, registry, understanding, context_store, *, research_signatures=()):
    context = request_context(payload, understanding)
    if research_signatures:
        context["conditions"] = list(dict.fromkeys(context.get("conditions", []) + ["research:" + sig for sig in research_signatures]))
    initial = deepcopy((payload.get("company_context") or {}).get("candidates", []))
    # These fields describe a computed view, never caller-granted authority.
    for candidate in initial:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str) or not candidate["id"]:
            raise ValueError("context candidate must be an identified object")
        for field in ("active", "applicable", "preferred", "applicable_line_ids", "preferred_line_ids", "resolution"):
            candidate.pop(field, None)
    info = {"enabled": context_store is not None, "loaded": False, "unresolved": [],
            "reason": "Private persistence not configured; cold start remains available."}
    private_view = None
    if context_store is not None:
        if type(payload.get("persist_references", True)) is not bool:
            raise ValueError("persist_references must be boolean")
        references = [c for c in initial if c.get("status") in {"public_reference", "working_value"}]
        if references and payload.get("persist_references", True):
            source_ids = {c.get("source_id") for c in references}
            context_store.record({"sources": [s for s in registry["sources"] if s["id"] in source_ids], "candidates": references})
        private_view = context_store.view(context)
        known_sources = {s["id"]: s for s in registry["sources"]}
        for source in private_view["sources"]:
            if source["id"] in known_sources and known_sources[source["id"]] != source:
                raise ValueError("private context source id conflicts with inquiry source")
            known_sources[source["id"]] = source
        registry["sources"] = list(known_sources.values())
        by_id = {c["id"]: c for c in initial}
        for candidate in private_view["candidates"]:
            candidate = deepcopy(candidate)
            if candidate["id"] in by_id:
                fields = ("key", "value", "status", "source_id", "scope", "scope_spec", "unit", "conditions", "provenance")
                if any(candidate.get(field) != by_id[candidate["id"]].get(field) for field in fields):
                    raise ValueError("context candidate id cannot overwrite retained evidence")
            by_id[candidate["id"]] = candidate
        initial = list(by_id.values())
        info = {"enabled": True, "loaded": bool(private_view["candidates"]),
                "schema_version": private_view["schema_version"], "unresolved": private_view["unresolved"],
                "candidate_count": len(private_view["candidates"]), "event_count": len(private_view["resolutions"]),
                "reason": "Scoped private evidence loaded; raw inquiry facts are never persisted as company truth."}
    # Both transient and persisted rules use the same validated projection.
    initial = ValueStore(registry).extend(initial).candidates
    structured = [c for c in initial if "scope_spec" in c]
    if structured:
        private_view = project_context({"sources": (private_view or {}).get("sources", []),
                                        "candidates": structured,
                                        "resolutions": (private_view or {}).get("resolutions", [])}, context)
        unresolved_ids = {cid for item in private_view["unresolved"] for cid in item["candidate_ids"]}
        projected = {c["id"]: c for c in private_view["candidates"]}
        for candidate in projected.values():
            candidate.pop("resolution", None)
            if candidate["id"] in unresolved_ids:
                candidate["resolution"] = "unresolved"
        initial = [projected.get(c["id"], c) for c in initial]
        info["unresolved"] = private_view["unresolved"]
        for item in private_view["unresolved"]:
            if item not in private_view["selections"]:
                private_view["selections"].append(item)
    sources = [s for s in registry["sources"] if s["kind"] in {"company_context", "operator_input"}]
    if sources:
        states = {s["status"] for s in sources}
        status = "read" if states == {"read"} else "partial" if "read" in states else "unread"
        registry["coverage"]["company_context"] = {"status": status, "source_ids": [s["id"] for s in sources]}
    info["pending_confirmations"] = [c["id"] for c in initial if c.get("status") in {"public_reference", "working_value"}
                                     and c.get("role") != "external" and c.get("active", True) and c.get("applicable", True)]
    return initial, info, private_view
