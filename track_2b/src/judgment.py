"""A shared state resolver and declarative policy evaluator; advice only."""
from pathlib import Path
import json
from decimal import Decimal
from business_facts import build

POLICIES = json.loads((Path(__file__).parent / "judgment_policies.json").read_text(encoding="utf-8"))


def _value_key(field, value):
    if type(value) in (int, float):
        return str(Decimal(str(value)).normalize())
    if isinstance(value, str):
        key = " ".join(value.casefold().split())
        if field == "unit":
            key = {"%": "percent", "pct": "percent", "百分比": "percent"}.get(key, key)
        return key
    return json.dumps(value)


def _resolve(facts, payload):
    state, conflicts, unresolved = {"as_of": payload.get("as_of")}, [], []
    grouped = {}
    for fact in facts:
        # A requested quantity is sufficient for PRELIMINARY costing; it is not
        # a confirmed order or authorization. Operational states need support.
        usable = fact["status"] == "supported" or (
            fact["field"] in ("product", "product_code", "quantity", "quantity_qualifier")
            and fact["stance"] in ("customer", "company"))
        if not usable:
            unresolved.append(fact)
            continue
        grouped.setdefault(fact["field"], []).append(fact)
    for field, group in grouped.items():
        values = {_value_key(field, f["value"]) for f in group}
        if len(values) > 1:
            conflicts.append(field)
        else:
            state[field] = group[0]["value"]
    if "product" not in state and "product_code" in state:
        state["product"] = state["product_code"]
    state["conflict"] = bool(conflicts)
    state["customer_payment_claim"] = any(f["field"] == "payment_status" and f["stance"] == "customer"
                                           and f["value"] == "received" for f in unresolved)
    return state, conflicts, unresolved


def _operand(item, state):
    return state.get(item["field"]) if isinstance(item, dict) else item


def _condition(condition, state):
    op, left = condition[0], _operand(condition[1], state)
    if op == "missing":
        return left is None
    if op == "present":
        return left is not None
    right = _operand(condition[2], state)
    if left is None or right is None:
        return False
    if op == "eq":
        return type(left) is type(right) and left == right
    if op == "ne":
        return left != right
    if type(left) in (int, float) and type(right) in (int, float):
        left, right = Decimal(str(left)), Decimal(str(right))
    return {"gt": lambda: left > right, "ge": lambda: left >= right,
            "lt": lambda: left < right, "le": lambda: left <= right}[op]()


def validate_output(result, sources):
    """Critical runtime invariants; contract shape/enums checked in acceptance tests."""
    if result["needs_human_approval"] is not True:
        raise ValueError("Human approval cannot be disabled")
    if not result["reason"] or not result["owner"]:
        raise ValueError("Missing judgment explanation or owner")
    ids = set()
    for fact in result["evidence"]:
        if fact["fact_id"] in ids or fact["source_id"] not in sources:
            raise ValueError("Invalid or duplicate evidence id")
        ids.add(fact["fact_id"])
        start, end = fact["span"]
        text = sources[fact["source_id"]]["text"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or text[start:end] != fact["quote"]:
            raise ValueError("Evidence does not point to its exact original source")
        party = sources[fact["source_id"]]["party"]
        allowed_stances = {party} | ({"customer_claimed_prior", "unattributed"} if party == "customer" else set())
        if fact["stance"] not in allowed_stances:
            raise ValueError("Evidence party was upgraded")
    for item in result["blocking_conditions"]:
        if not set(item["evidence_ids"]) <= ids:
            raise ValueError("Blocking condition cites unknown evidence")


def judge(payload):
    facts, sources = build(payload)
    state, conflicts, unresolved = _resolve(facts, payload)
    policy = POLICIES[payload["scenario"]]
    gaps = [field for field in policy["required"] if state.get(field) is None]
    rules = POLICIES["common_rules"] + ([] if gaps else policy["rules"])
    matched = next((r for r in rules if all(_condition(c, state) for c in r["when"])), policy["default"])
    blockers = [{"field": field, "reason": "该项缺失或没有可用于当前判断的已验证来源。",
                 "evidence_ids": [f["fact_id"] for f in facts if f["field"] == field],
                 "blocks_current_action": False, "scope": policy["scope"]} for field in gaps]
    blockers.extend({"field": field, "reason": "同一对象存在不同值；保留来源并由人工解决冲突。",
                     "evidence_ids": [f["fact_id"] for f in facts if f["field"] == field],
                     "blocks_current_action": False, "scope": policy["scope"]} for field in conflicts)
    blockers.extend({"field": f["field"], "reason": "该来源主张未获我方确认，或测量缺少自身单位/指标。",
                     "evidence_ids": [f["fact_id"]], "blocks_current_action": False, "scope": policy["scope"]}
                    for f in unresolved)
    blockers.extend({"field": field, "reason": "商业确认仍需有授权来源和人工批准。",
                     "evidence_ids": [f["fact_id"] for f in facts if f["field"] == field],
                     "blocks_current_action": False, "scope": "commercial_commitment"}
                    for field in policy.get("approvals", []) if state.get(field) is not True)
    for field in matched.get("unmet", []):
        blockers.append({"field": field, "reason": matched["reason"],
                         "evidence_ids": [f["fact_id"] for f in facts if f["field"] == field],
                         "blocks_current_action": False, "scope": policy["scope"]})
    result = {"schema_version": "1.0", "scenario": payload["scenario"],
              "action": matched["action"], "owner": matched["owner"], "reason": matched["reason"],
              "evidence": facts, "blocking_conditions": blockers,
              "needs_human_approval": True, "next_customer_action": matched["next_customer_action"],
              "confidence": "low" if gaps or conflicts else "medium" if unresolved or blockers else "high"}
    validate_output(result, sources)
    return result
