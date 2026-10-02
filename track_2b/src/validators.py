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
    email_digits = _digits_of(_month_normalized(email))

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
    """Numbers in the draft must exist in the email (digit-wise, month-name aware);
    catches invented figures."""
    issues = []
    if not draft:
        return {"ok": False, "issues": ["empty_draft"]}
    draft_m, email_m = _month_normalized(draft), _month_normalized(email)
    email_digits = _digits_of(email_m)
    model_numbers = set(re.findall(r"\d[\d,.]*\d|\d", draft_m))
    for n in model_numbers:
        d = _digits_of(n)
        if d and d not in email_digits:
            issues.append(f"invented_number:{n}")
    return {"ok": not issues, "issues": issues}


DATE_TOKEN = re.compile(r"\d{1,2}\s*月\s*\d{1,2}[日号]?|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|week\s*\d+|\d+\s*(?:个?工作日|天|日|weeks?|days?)", re.I)
PROMISE_VERB = re.compile(r"将于|会在?|预计| guarantee|will (?:deliver|ship|send|provide|arrive)|delivery (?:by|on)|ETA|ETD", re.I)
MONTHS = {"jan": "1", "feb": "2", "mar": "3", "apr": "4", "may": "5", "jun": "6",
          "jul": "7", "aug": "8", "sep": "9", "sept": "9", "oct": "10", "nov": "11", "dec": "12"}


def _month_normalized(text):
    """Map English month names to their numbers so 'Dec 1' and '12月1日' digit-compare equal."""
    t = str(text or "").lower()
    for name, num in MONTHS.items():
        t = re.sub(rf"\b{name}\.?\s*", f"{num}月", t)
    return t


def _num_tokens(text):
    return set(t for t in re.split(r"\D+", _month_normalized(text)) if t)


def check_claims(draft, email):
    """Unsupported factual claims (mechanical proxy):
    a date/duration token appearing in the draft whose component numbers are NOT all present
    in the email (month-name aware) is flagged. Numbers are covered by check_draft."""
    issues = []
    if not draft:
        return {"ok": False, "issues": ["empty_draft"]}
    email_tokens = _num_tokens(email)
    for m in DATE_TOKEN.finditer(_month_normalized(draft)):
        comps = [t for t in re.split(r"\D+", m.group(0)) if t]
        if comps and not all(c in email_tokens for c in comps):
            issues.append(f"unsupported_date_or_duration:{m.group(0)}")
    return {"ok": not issues, "issues": issues}
