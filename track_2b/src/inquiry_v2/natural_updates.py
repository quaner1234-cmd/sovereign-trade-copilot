"""Small explicit operator edit grammar; ambiguous or partial commands do not write."""
import re
from .scope import normalize_scope

NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
MOQ = re.compile(rf"(?:MOQ|起订量)\s*(?:(?:改为|改成|改|调整为|设为|is|to|=)\s*)?(?P<value>{NUMBER})\s*(?:件|pcs|pieces?)?\s*(?P<basis>每款|per\s+style|每色|per\s+colou?r)?", re.I)
LEAD = re.compile(rf"(?:正常交期|常规交期|normal\s+lead\s*time|standard\s+lead\s*time)\s*(?:(?:改为|改成|改|调整为|设为|is|to|=)\s*)?(?P<value>{NUMBER})\s*(?:天|days?)", re.I)


def parse_edits(text, view, scope_spec, target_ids=None):
    """Return at most five complete typed changes, without changing the ledger.

    Scope is supplied by the trusted operator, never inferred from customer mail.
    Omitted units and conditions retain the explicit edited candidate's meaning.
    """
    scope = normalize_scope(scope_spec)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("explicit edit text required")
    if target_ids is not None and (not isinstance(target_ids, list) or any(not isinstance(i, str) for i in target_ids)):
        raise ValueError("target_ids must be candidate ids")
    candidates = view.get("candidates", [])
    by_id = {c["id"]: c for c in candidates}
    if target_ids and any(i not in by_id for i in target_ids):
        raise ValueError("unknown edit target")
    clauses = [p.strip().rstrip("。.") for p in re.split(r"[，；;\n]|,(?!\d{3}(?:\D|$))", text) if p.strip()]
    if not clauses or len(clauses) > 5:
        raise ValueError("one to five complete changes required")
    changes, seen = [], set()
    for clause in clauses:
        moq, lead = MOQ.fullmatch(clause), LEAD.fullmatch(clause)
        if not moq and not lead:
            raise ValueError("unrecognized edit clause; no changes applied")
        match = moq or lead
        value = int(match.group("value").replace(",", ""))
        if value <= 0:
            raise ValueError("edit values must be positive")
        family = "moq." if moq else "lead_time."
        requested_key = ("moq.per_colour" if moq and re.search(r"色|colou?r", moq.group("basis") or "", re.I)
                         else "moq.style" if moq and moq.group("basis") else "moq.general" if moq else "lead_time.normal")
        pool = [c for c in candidates if c.get("active", True) and c.get("status") in {"public_reference", "working_value", "company_confirmed"}
                and c.get("key", "").startswith(family) and c.get("scope_spec") == scope]
        if moq and moq.group("basis"):
            pool = [c for c in pool if c["key"] == requested_key]
        if lead and not target_ids:
            # A normal production lead-time command must not silently edit a
            # sample-only estimate simply because it is the only stored value.
            pool = [c for c in pool if c["key"] in {"lead_time.normal", "lead_time.bulk", "lead_time.standard"}]
        if target_ids:
            pool = [c for c in pool if c["id"] in target_ids]
        else:
            ranks = {"company_confirmed": 5, "working_value": 3, "public_reference": 1}
            best = max((ranks[c["status"]] for c in pool), default=0)
            pool = [c for c in pool if ranks[c["status"]] == best]
        if len(pool) > 1:
            raise ValueError("edit target is unresolved; specify the candidate to adjudicate")
        if target_ids and not pool:
            raise ValueError("explicit target does not match the edit field and scope")
        old = pool[0] if pool else None
        key = old["key"] if old else requested_key
        if key in seen:
            raise ValueError("duplicate edit field; no changes applied")
        seen.add(key)
        unit = old.get("unit") if old else ("pcs/style" if key == "moq.style" else "pcs/colour" if key == "moq.per_colour" else "pcs" if moq else "days")
        change = {"key": key, "value": value, "unit": unit,
                  "conditions": old.get("conditions", []) if old else ([] if moq else ["normal_conditions"])}
        if old:
            change["candidate_id"] = old["id"]
        changes.append(change)
    return changes


def apply_text(store, text, *, actor, scope_spec, target_ids=None):
    changes = parse_edits(text, store.view(), scope_spec, target_ids)
    return store.apply_edits(changes, actor=actor, statement=text, scope_spec=scope_spec)
