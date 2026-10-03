"""Optional research planning; no implicit network access or fabricated findings."""
import re


def plan(registry, options=None):
    options = options or {}
    if not isinstance(options, dict) or type(options.get("enabled", False)) is not bool:
        raise ValueError("research.enabled must be boolean")
    sources = registry["sources"]
    refs = [s["id"] for s in sources if s["kind"] in {"public_source", "referenced_url"}
            and s["status"] == "read"]
    pending = [{"source_id": s["id"], "task": "Read the referenced product source before re-asking.",
                "changes_decision": "Current product and specification basis", "status": s["status"]}
               for s in sources if s["kind"] == "referenced_url" and s["status"] != "read"]
    text = " ".join(s["text"] for s in sources if s["party"] == "customer" and s["status"] == "read")
    if re.search(r"\b(licensed|traceability|authori[sz]ed|certificat\w*|supplier)\b", text, re.I):
        pending.append({"source_id": None, "task": "Verify only the decision-relevant supplier/material route in primary public sources.",
                        "changes_decision": "Sourcing options to check internally; no company capability confirmation", "status": "not_run"})
    return {"enabled": options.get("enabled", False), "ran": False, "refs": refs,
            "reason": "Read sources supplied by the caller; no network adapter executed in P0-P2." if refs else
                      "Optional network research not executed; core judgment runs with explicit coverage gaps.",
            "pending": pending, "issues": []}
