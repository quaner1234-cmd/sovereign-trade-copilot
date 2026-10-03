"""Candidate ledger: preserve all evidence and resolve only within exact scope."""
from copy import deepcopy
import re
import math
from .contract import VALUE_STATUSES


def _value_present(value, quote, key=None):
    if value is None:
        return True
    if isinstance(value, list):
        return all(_value_present(v, quote, key) for v in value)
    if isinstance(value, dict):
        recognized = {"min", "max", "value"} & set(value)
        return bool(recognized) and not set(value) - recognized and all(_value_present(value[k], quote, key) for k in recognized)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numbers = [float(n.replace(",", "")) for n in re.findall(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?![\w.-])", quote)]
        spelled = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                   "seven": 7, "eight": 8, "nine": 9, "ten": 10, "single": 1, "a": 1,
                   "an": 1, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3}
        numbers.extend(spelled[t] for t in re.findall(r"\b\w+\b", quote.lower()) if t in spelled)
        if key == "quantity":
            from .understand import QTY_RE, _number
            for match in QTY_RE.finditer(quote):
                numbers.append(_number(match.group("first")))
                if match.group("second"):
                    numbers.append(_number(match.group("second")))
        return float(value) in numbers
    if key == "payment_terms":
        from .understand import PAYMENT_RE
        return re.sub(r"\s+", "", str(value)).casefold() in {
            re.sub(r"\s+", "", m.group()).casefold() for m in PAYMENT_RE.finditer(quote)}
    return str(value).casefold() in quote.casefold()


class ValueStore:
    def __init__(self, registry):
        self.sources = {s["id"]: s for s in registry["sources"]}
        self.candidates = []
        self.issues = []

    def add(self, candidate):
        if not isinstance(candidate, dict):
            raise ValueError("value candidate must be an object")
        c = deepcopy(candidate)
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            raise ValueError("value candidate id required")
        old = next((v for v in self.candidates if v["id"] == cid), None)
        if old is not None:
            if old != c:
                raise ValueError("value candidate cannot overwrite an existing id")
            return old
        if not isinstance(c.get("status"), str) or c["status"] not in VALUE_STATUSES or not isinstance(c.get("key"), str) or not c["key"] or not isinstance(c.get("scope"), str) or not c["scope"]:
            raise ValueError("value candidate requires key, scope and valid status")
        source = self.sources.get(c.get("source_id"))
        provenance = c.get("provenance") or {}
        if not isinstance(provenance, dict):
            raise ValueError("value provenance must be an object")
        quote, span = provenance.get("quote"), provenance.get("span")
        reasons = []
        value = c.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
            raise ValueError("value candidates require finite numbers")
        if isinstance(value, bool) or isinstance(value, list) and (not value or any(not isinstance(v, str) or not v.strip() for v in value)):
            reasons.append("value_shape_invalid")
        if c["status"] != "unknown":
            if not source or source["status"] != "read":
                reasons.append("value_source_unread")
            elif not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span) or not (0 <= span[0] < span[1] <= len(source["text"])) or source["text"][span[0]:span[1]] != quote:
                reasons.append("value_source_span_invalid")
            elif not _value_present(c.get("value"), quote, c["key"]):
                reasons.append("value_not_in_evidence")
        if c["status"] == "company_confirmed":
            if not source or source["kind"] not in {"company_context", "operator_input"} or source["party"] != "company":
                reasons.append("company_authority_invalid")
            elif not all(source["metadata"].get(k) for k in ("confirmed_by", "confirmed_at")) or c["scope"] != source["scope"]:
                reasons.append("company_confirmation_or_scope_missing")
        if c["status"] == "public_reference" and source and source["kind"] not in {"public_source", "referenced_url"}:
            reasons.append("public_authority_invalid")
        if c["status"] == "customer_stated" and (not source or source["party"] != "customer"):
            reasons.append("customer_authority_invalid")
        if c["status"] == "system_reported" and (not source or source["kind"] != "platform_field"):
            reasons.append("platform_authority_invalid")
        if c["status"] == "working_value" and not all(provenance.get(k) for k in ("derived_from", "owner", "confirmation_point")):
            reasons.append("working_value_basis_missing")
        if c["status"] == "working_value" and (not source or source["party"] != "company"):
            reasons.append("working_value_owner_invalid")
        if reasons:
            c["requested_status"] = c["status"]
            c["status"] = "rejected"
            c["rejection_reasons"] = reasons
            self.issues.extend(reason + ":" + cid for reason in reasons)
        self.candidates.append(c)
        return c

    def extend(self, candidates):
        for candidate in candidates:
            self.add(candidate)
        return self

    def select(self, key, scope):
        rank = {"company_confirmed": 5, "customer_stated": 4, "working_value": 3,
                "system_reported": 2, "public_reference": 1}
        pool = [c for c in self.candidates if c["key"] == key and c["scope"] == scope and c["status"] in rank]
        if not pool:
            return {"candidate_id": None, "status": "unknown", "issues": []}
        best = max(rank[c["status"]] for c in pool)
        winners = [c for c in pool if rank[c["status"]] == best]
        def identity(candidate):
            return candidate.get("value"), candidate.get("unit"), candidate.get("conditions", [])
        if any(identity(c) != identity(winners[0]) for c in winners):
            return {"candidate_id": None, "status": "unresolved", "issues": ["same_scope_value_conflict"],
                    "candidate_ids": [c["id"] for c in winners]}
        return {"candidate_id": winners[0]["id"], "status": winners[0]["status"], "issues": []}
