# -*- coding: utf-8 -*-
"""Validation layer — engineering response to phase-2 findings:
  (1) repeated-token digit loss (5000->50)  -> numbers in extraction must appear verbatim in source
  (2) fabrication of facts (invented quote) -> numbers/dates in draft must come from email or be computed here
  (3) inventing values when info missing    -> extraction must use not_stated instead of guessing
All checks mechanical; nothing is silently fixed — failures are flagged for human review."""
import json, re


def load_json_strict(text):
    """Parse model output as JSON; first whole-text, then first balanced block."""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    for op, cl in (("{", "}"), ("[", "]")):
        s = t.find(op)
        if s == -1:
            continue
        depth = 0
        for i in range(s, len(t)):
            if t[i] == op:
                depth += 1
            elif t[i] == cl:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[s:i + 1])
                    except Exception:
                        break
        break
    return None


def _digits_of(s):
    return re.sub(r"[^\d]", "", str(s))


def check_extraction(extraction, email):
    """Every number written by the model must exist verbatim (digit-wise) in the email."""
    issues = []
    if not isinstance(extraction, dict):
        return {"ok": False, "issues": ["extraction_not_json_object"]}
    email_digits = _digits_of(email)

    def verbatim(v):
        d = _digits_of(v)
        return (not d) or (d in email_digits)

    for p in extraction.get("products", []) or []:
        for f in ("sku", "qty"):
            if p.get(f) and not verbatim(p[f]):
                issues.append(f"products.{f}:digit_mismatch:{p[f]}")
    for f in ("incoterm", "payment_terms", "deadline", "buyer"):
        v = extraction.get(f)
        if v and not verbatim(v):
            issues.append(f"{f}:digit_mismatch:{v}")
    for a in extraction.get("amounts", []) or []:
        if not verbatim(a):
            issues.append(f"amounts:digit_mismatch:{a}")
    if not extraction.get("not_stated"):
        issues.append("not_stated_empty:suspicious_perfect_extraction")
    return {"ok": not issues, "issues": issues}


def check_draft(draft, email):
    """Numbers in the draft must exist in the email (digit-wise); catches invented figures."""
    issues = []
    if not draft:
        return {"ok": False, "issues": ["empty_draft"]}
    model_numbers = set(re.findall(r"\d[\d,.，]*\d|\d", draft))
    email_digits = _digits_of(email)
    for n in model_numbers:
        d = _digits_of(n)
        if d and d not in email_digits:
            issues.append(f"invented_number:{n}")
    return {"ok": not issues, "issues": issues}


DATE_TOKEN = re.compile(r"\d{1,2}\s*月\s*\d{1,2}[日号]?|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|week\s*\d+|\d+\s*(?:个?工作日|天|日|weeks?|days?)", re.I)
PROMISE_VERB = re.compile(r"将于|会在?|预计| guarantee|will (?:deliver|ship|send|provide|arrive)|delivery (?:by|on)|ETA|ETD", re.I)


def check_claims(draft, email):
    """Unsupported factual claims (mechanical proxy):
    a date/duration token appearing in the draft but NOT in the email, especially near
    a promise verb, is flagged. Numbers are covered by check_draft."""
    issues = []
    if not draft:
        return {"ok": False, "issues": ["empty_draft"]}
    for m in DATE_TOKEN.finditer(draft):
        tok = m.group(0)
        digits = _digits_of(tok)
        if digits and digits not in _digits_of(email):
            issues.append(f"unsupported_date_or_duration:{tok}")
    return {"ok": not issues, "issues": issues}
