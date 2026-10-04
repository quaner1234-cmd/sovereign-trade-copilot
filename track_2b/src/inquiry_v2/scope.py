"""Explicit applicability constraints; unknown dimensions never imply a match."""
from copy import deepcopy
import hashlib
import json
import math


def normalize_scope(spec):
    if not isinstance(spec, dict) or not spec:
        raise ValueError("scope_spec must explicitly declare applicability")
    allowed = {"global", "product_categories", "markets", "quantity_range", "conditions", "project_id"}
    if set(spec) - allowed:
        raise ValueError("unknown applicability dimension")
    result = {}
    if "global" in spec:
        if spec["global"] is not True or len(spec) != 1:
            raise ValueError("global:true must be an explicit standalone scope")
        return {"global": True}
    for name in ("product_categories", "markets", "conditions"):
        if name in spec:
            items = spec[name]
            if not isinstance(items, list) or not items or any(not isinstance(v, str) or not v.strip() for v in items):
                raise ValueError(name + " requires nonempty strings")
            result[name] = sorted({v.strip().casefold() for v in items})
    if "project_id" in spec:
        if not isinstance(spec["project_id"], str) or not spec["project_id"].strip():
            raise ValueError("project_id requires an explicit identity")
        result["project_id"] = spec["project_id"].strip()
    if "quantity_range" in spec:
        interval = spec["quantity_range"]
        if not isinstance(interval, dict) or not interval or set(interval) - {"min", "max", "unit"} or not ({"min", "max"} & set(interval)):
            raise ValueError("quantity_range requires min and/or max")
        for name in ("min", "max"):
            if name in interval and (type(interval[name]) not in (int, float) or not math.isfinite(interval[name]) or interval[name] < 0):
                raise ValueError("quantity interval requires finite nonnegative numbers")
        if interval.get("min", 0) > interval.get("max", float("inf")):
            raise ValueError("quantity interval is reversed")
        if "unit" in interval and (not isinstance(interval["unit"], str) or not interval["unit"].strip()):
            raise ValueError("quantity unit must be a string")
        result["quantity_range"] = deepcopy(interval)
        if "unit" in interval:
            result["quantity_range"]["unit"] = interval["unit"].strip().casefold()
    if not result:
        raise ValueError("scope cannot infer global applicability")
    return result


def scope_token(spec):
    canonical = json.dumps(normalize_scope(spec), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "company.scope:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def scope_matches(spec, context):
    spec = normalize_scope(spec)
    if spec.get("global"):
        return True
    context = context or {}
    if not isinstance(context, dict):
        raise ValueError("request_context must be an object")
    for name in ("product_categories", "markets"):
        if name in spec:
            actual = context.get(name, [])
            if isinstance(actual, str):
                actual = [actual]
            if not isinstance(actual, list) or not actual:
                return False
            if name == "product_categories":
                from .understand import canonical_product
                allowed = [canonical_product(v) for v in spec[name]]
                if not all(any(canonical_product(v) == category or canonical_product(v).endswith(" " + category)
                               for category in allowed) for v in actual):
                    return False
            elif not set(str(v).strip().casefold() for v in actual) <= set(spec[name]):
                return False
    if "conditions" in spec:
        actual = context.get("conditions", [])
        if not isinstance(actual, list) or not set(spec["conditions"]) <= {str(v).strip().casefold() for v in actual}:
            return False
    if "project_id" in spec and context.get("project_id") != spec["project_id"]:
        return False
    if "quantity_range" in spec:
        value = context.get("quantity", context.get("quantity_range"))
        if type(value) in (int, float):
            if not math.isfinite(value):
                return False
            low = high = value
        elif isinstance(value, dict):
            if {"min", "max"} & set(value):
                provided = [value[name] for name in ("min", "max") if name in value]
                if any(type(n) not in (int, float) or not math.isfinite(n) or n < 0 for n in provided):
                    return False
                low, high = value.get("min", 0), value.get("max", float("inf"))
            elif "value" in value and type(value["value"]) in (int, float) and math.isfinite(value["value"]):
                low = high = value["value"]
            else:
                return False
        else:
            return False
        if any(type(n) not in (int, float) or math.isnan(n) for n in (low, high)) or low < 0 or low > high:
            return False
        interval = spec["quantity_range"]
        unit = context.get("quantity_unit", context.get("unit", value.get("unit") if isinstance(value, dict) else None))
        def count_unit(value):
            normalized = str(value).strip().casefold()
            return "pcs" if normalized in {"pcs", "pc", "piece", "pieces"} else normalized
        if interval.get("unit") and (not isinstance(unit, str) or count_unit(unit) != count_unit(interval["unit"])):
            return False
        if low < interval.get("min", 0) or high > interval.get("max", float("inf")):
            return False
    return True


def specificity(spec):
    """A project or a constrained company rule outranks a global default."""
    spec = normalize_scope(spec)
    return 0 if spec.get("global") else len(spec) + (3 if "project_id" in spec else 0)
