"""Inquiry judgment and optional human-reviewed first reply. No execution."""

SCHEMA_VERSION = "v2-inquiry-1.0"
SOURCE_KINDS = {"customer_email", "thread_message", "attachment", "platform_field",
                "referenced_url", "public_source", "company_context", "operator_input"}
VALUE_STATUSES = {"customer_stated", "system_reported", "public_reference", "working_value",
                  "company_confirmed", "unknown", "rejected"}
ACTIONS = {"ALIGN_MOQ", "INTERNAL_COSTING", "INTERNAL_VERIFICATION", "ASSESS_COMPANY_FIT",
           "VERIFY_SAMPLE_ROUTE", "REQUEST_INFORMATION", "RESEARCH", "OUT_OF_SCOPE"}


def validate_output(result, registry=None):
    if result.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid inquiry schema version")
    for field in ("understanding", "assessment", "advance", "reply", "trust"):
        if not isinstance(result.get(field), dict):
            raise ValueError("missing inquiry output section: " + field)
    advance = result["advance"]
    if advance.get("action") not in ACTIONS:
        raise ValueError("only reversible advisory actions are allowed")
    for field in ("action", "owner", "reason", "next_state"):
        if not isinstance(advance.get(field), str) or not advance[field].strip():
            raise ValueError("advance requires " + field)
    questions = advance.get("customer_questions", [])
    if not isinstance(questions, list) or len(questions) > 3 or any(not isinstance(q, dict) or not q.get("changes_decision") or not q.get("no_re_ask_basis") for q in questions):
        raise ValueError("customer questions require decision relevance and a maximum of three")
    assessment = result["assessment"]
    for field in ("current_key_uncertainty", "decision_barrier", "hard_blocker"):
        if field not in assessment:
            raise ValueError("missing separate assessment: " + field)
    if assessment["current_key_uncertainty"].get("klass") not in {"A", "B", "C", "D", "E"}:
        raise ValueError("unknown classification must be A-E")
    blocker = assessment["hard_blocker"]
    if blocker is not None and not all(blocker.get(k) is True for k in
            ("affects_current_decision", "no_low_cost_alternative", "no_useful_advance")):
        raise ValueError("hard blocker must satisfy all three criteria")
    if result["trust"].get("needs_human_approval") is not True:
        raise ValueError("human approval cannot be removed")
    if result["reply"].get("language") != result["understanding"].get("customer_language"):
        raise ValueError("reply language must equal customer language")
    reply = result["reply"]
    if reply.get("status") not in {"not_composed", "ready_for_review", "withheld", "unavailable"}:
        raise ValueError("unknown reply status")
    if reply.get("draft") is not None:
        if (reply.get("status") != "ready_for_review" or not isinstance(reply["draft"], str)
                or not reply["draft"].strip() or reply.get("needs_human_approval") is not True
                or reply.get("guard", {}).get("passed") is not True):
            raise ValueError("composed reply requires passed gates and human approval")
    elif reply.get("status") == "ready_for_review":
        raise ValueError("ready reply requires a draft")
    if registry is not None:
        sources = {s["id"]: s for s in registry["sources"]}
        evidence_ids = set()
        for item in result["trust"].get("evidence", []):
            source = sources.get(item.get("source_id"))
            span = item.get("span", [])
            if not source or source["status"] != "read" or len(span) != 2 or any(type(n) is not int for n in span) or not (0 <= span[0] < span[1] <= len(source["text"])) or source["text"][span[0]:span[1]] != item.get("quote"):
                raise ValueError("evidence requires an exact readable source span")
            if item.get("id") in evidence_ids:
                raise ValueError("duplicate evidence id")
            evidence_ids.add(item.get("id"))
        if not set(advance.get("evidence_ids", [])) <= evidence_ids:
            raise ValueError("advance cites unknown evidence")
        candidate_ids = {c["id"] for c in result["values"] if c["status"] not in {"rejected", "unknown"}}
        if not set(advance.get("value_candidate_ids", [])) <= candidate_ids:
            raise ValueError("advance cites a rejected or unknown value")
    return result
