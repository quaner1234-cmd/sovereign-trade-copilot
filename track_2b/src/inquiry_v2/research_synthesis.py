"""Recommend observed planning values, without converting variability to truth."""
from datetime import timedelta
import hashlib
import json
from .research_evidence import now_utc


def synthesize(task, observations, sources, now=None):
    now = now or now_utc()
    result = {"topic": task["topic"], "role": task["role"], "line_id": task["line_id"], "signature": task["signature"],
              "observed_values": [{"candidate_id": c["id"], "value": c["value"], "unit": c["unit"],
                                   "publisher": c["provenance"]["publisher"], "conditions": c["conditions"]} for c in observations],
              "source_count": len({c["provenance"]["publisher"] for c in observations}),
              "range": None, "recommended_working_value": None, "recommendation_basis": None,
              "confidence": "low", "conflicts": [], "limitations": [], "status": "unknown"}
    if not observations:
        result["limitations"].append("No reliable, comparable, literal source evidence; no value generated.")
        return result, [], []
    if any(c["provenance"].get("product_scope") == "general_category" for c in observations):
        result["limitations"].append("General category/manufacturing policy is not a product-specific quotation or applicability ruling.")
    if all(isinstance(c["value"], str) for c in observations):
        result.update(status="reference_only", confidence="medium")
        result["limitations"] += ["External primary-source reference; applicability and company capability remain separate.",
                                  "Distinct source statements are retained separately; unstructured contradictions require human review."]
        return result, [], []
    groups = {}
    for candidate in observations:
        group = (candidate["key"], candidate["unit"], tuple(candidate["conditions"]))
        groups.setdefault(group, []).append(candidate)
    for group, pool in groups.items():
        issuer_values = {}
        for c in pool:
            if isinstance(c["value"], (int, float, dict)):
                issuer_values.setdefault(c["provenance"]["publisher"], set()).add(json.dumps(c["value"], sort_keys=True))
        for issuer, values in issuer_values.items():
            if len(values) > 1:
                result["conflicts"].append({"publisher": issuer, "group": list(group[:2]), "candidate_ids": [c["id"] for c in pool if c["provenance"]["publisher"] == issuer]})
    if result["conflicts"]:
        result.update(status="unresolved", recommendation_basis="Conflicting same-policy evidence requires review; no averaging.")
        result["limitations"].append("Contradictory evidence remains in the candidate ledger.")
        return result, [], []
    basis = task["comparable"].get("requested_basis")
    if task["topic"] == "moq" and basis:
        groups = {group: pool for group, pool in groups.items() if group[1] == "pcs/" + basis}
        result["limitations"].append("Recommendation considers only the explicitly requested MOQ basis; other observations are retained.")
    if len(groups) != 1:
        result["status"] = "incomparable"
        result["limitations"].append("Different units, currencies or commercial bases cannot be pooled.")
        return result, [], []
    pool = next(iter(groups.values()))
    result["comparable_source_count"] = len({c["provenance"]["publisher"] for c in pool})
    result["applicability_conditions"] = pool[0]["conditions"]
    numeric = [c for c in pool if isinstance(c["value"], (int, float, dict))]
    if not numeric:
        result.update(status="reference_only", confidence="high" if task["topic"] in {"compliance", "shipping"} else "medium")
        result["limitations"].append("External primary-source reference; applicability and company capability remain separate.")
        result["limitations"].append("Distinct source statements are retained separately; unstructured contradictions require human review.")
        return result, [], []
    lows = [c["value"].get("min") if isinstance(c["value"], dict) else c["value"] for c in numeric]
    highs = [c["value"].get("max") if isinstance(c["value"], dict) else c["value"] for c in numeric]
    result["range"] = {"min": min(lows), "max": max(highs), "unit": pool[0]["unit"]}
    required = 2 if task["role"] == "company_specific" else 1
    if result["comparable_source_count"] < required:
        result["status"] = "range_only"
        result["limitations"].append("A single supplier is not enough to recommend a company planning value.")
        return result, [], []
    exact = [c for c in numeric if not isinstance(c["value"], dict) and not c.get("approximate")]
    if not exact:
        result["status"] = "range_only"
        result["limitations"].append("Sources publish ranges only; no exact observed value supports a point recommendation.")
        return result, [], []
    # One vote per independent publisher; no mean, midpoint or unit conversion.
    values = {}
    for c in exact:
        values[c["provenance"]["publisher"]] = c["value"]
    if task["role"] == "company_specific" and len(values) < 2:
        result["status"] = "range_only"
        result["limitations"].append("Insufficient independent exact observations for a precise working value.")
        return result, [], []
    ordered = sorted(values.values())
    point = ordered[len(ordered) // 2]
    support = next(c for c in exact if c["value"] == point)
    result.update(status="working_value" if task["role"] == "company_specific" else "reference_only",
                  recommended_working_value={"value": point, "unit": support["unit"], "key": support["key"]},
                  recommendation_basis="Observed upper median across independent publishers; no averaging or invented midpoint.",
                  confidence="medium" if max(highs) / min(lows) <= 3 else "low")
    if any(c["provenance"].get("product_scope") == "general_category" for c in pool):
        result["confidence"] = "low"
    result["limitations"] += ["Public self-reports are planning references, not our company terms."] if task["role"] == "company_specific" else ["Published external transit reference is not a guaranteed shipment arrival."]
    if max(highs) / min(lows) > 3:
        result["limitations"].append("Wide observed dispersion; scope and exception review are required.")
    if task["role"] != "company_specific":
        return result, [], []
    quote = "Provisional planning value for " + support["key"] + ": " + str(point) + " " + support["unit"] + ". Company value remains unconfirmed."
    source_id = "working-source-" + hashlib.sha256((task["signature"] + quote + now.isoformat()).encode()).hexdigest()[:22]
    source = {"id": source_id, "kind": "operator_input", "party": "company", "status": "read", "text": quote,
              "scope": "research:" + task["signature"], "metadata": {"generated_by": "public_reference_synthesis",
              "authorization": "reversible_working_assumption_only"}}
    candidate = {"id": "working-" + source_id[15:], "key": support["key"], "value": point, "unit": support["unit"],
                 "scope": source["scope"], "scope_spec": support["scope_spec"], "source_id": source_id,
                 "status": "working_value", "role": "company_specific", "conditions": support["conditions"],
                 "confidence": result["confidence"], "provenance": {"quote": quote, "span": [0, len(quote)],
                 "derived_from": [c["id"] for c in numeric], "owner": "sales+business_owner",
                 "confirmation_point": "Confirm/Edit before any company-specific customer claim or firm commitment",
                 "recommendation_basis": result["recommendation_basis"], "research_signature": task["signature"],
                 "review_on": (now + timedelta(days=task["ttl_days"])).isoformat()}}
    result["working_candidate_id"] = candidate["id"]
    return result, [source], [candidate]
