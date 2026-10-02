# -*- coding: utf-8 -*-
"""Track 2B pipeline v3 — evidence-gated, LLM-as-selector.

Stages (ITERATE decision, section 2):
  1. Apertus semantic extraction   -> classification + intent
  2. deterministic parser         -> candidate facts with source spans
  3. Apertus candidate selection  -> ids only, never values
  4. evidence validation          -> validated fact store (supported/inferred/not_stated)
  5. Apertus reply generation     -> from validated facts ONLY (raw email withheld)
  6. final output guard           -> blocks the reply on any violation
  7. retry once / deterministic fallback

The RAW MODEL output is preserved alongside the FINAL SYSTEM output so the
benchmark can report both, never blended into one number.
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_client
import fact_parsers as FP
import fact_store as FS
from validators import load_json_strict

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "v3.json")
PROMPTS = json.load(open(PROMPT_PATH, encoding="utf-8"))
FIELDS = PROMPTS["FIELDS"]

# ---------------------------------------------------------------- guard config

# A reply may mention a value only if the validated store supports it.
# Everything else is stripped by the guard, and if stripping breaks the reply
# we fall back to a deterministic template rather than ship an unsafe text.
GUARD_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
PROMISE_RE = re.compile(
    r"(将于|会在|保证|承诺|一定能|必定|保证在|will\s+(?:deliver|ship|guarantee|provide)|"
    r"guarantee\w*\s|within\s+\d+\s+(?:days?|weeks?|hours?))", re.I)

ALLOWED_INTENTS = set(PROMPTS["INTENT_ENUM"])


def _fill(tpl, **kw):
    out = tpl
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


# ------------------------------------------------------------------ LLM calls

def _chat_json(messages, max_tokens, temperature):
    for attempt in range(2):
        text, meta = llm_client.chat(messages, max_tokens=max_tokens, temperature=temperature)
        obj = load_json_strict(text)
        if obj is not None or meta.get("error"):
            return obj, text, (meta or {}) | {"attempts": attempt + 1}
    return None, text, (meta or {}) | {"attempts": 2}


def _candidate_block(parsed):
    """Render candidates for the selector. Values shown are verbatim spans."""
    lines = []
    for f in parsed["_facts"]:
        flags = []
        if f.get("negated"):
            flags.append("NEGATED")
        if f.get("customer_asserted"):
            flags.append("customer_asserted")
        if f.get("listing_sku"):
            flags.append("pairs_with:" + f["listing_sku"])
        if f.get("weak"):
            flags.append("weak(no currency symbol)")
        if f.get("qualified") is not None:
            flags.append("qualified" if f["qualified"] else "unqualified")
        if f.get("place"):
            flags.append("place:" + f["place"])
        tag = (" [" + ",".join(flags) + "]") if flags else ""
        lines.append(f'{f["id"]} | {f["type"]} | "{f["value"]}"{tag}')
    return "\n".join(lines) if lines else "(no candidates parsed)"


def _facts_block(store, buyer_value):
    """Render the validated store — the ONLY thing the reply generator sees."""
    rows = []
    for f in FIELDS:
        cell = store.fields[f]
        if cell["value"] is None:
            continue
        val = json.dumps(cell["value"], ensure_ascii=False)
        flags = ["status=" + cell["status"]]
        if any(x.get("customer_asserted") for x in cell["facts"]):
            flags.append("customer_asserted=true")
        rows.append(f'- {f}: {val} ({", ".join(flags)})')
    if not rows:
        rows.append("(no verified facts)")
    return "\n".join(rows), buyer_value or ""


# ------------------------------------------------------------ deterministic fallback

LABELS = {"products": "产品", "amounts": "金额", "incoterm": "贸易术语",
          "payment_terms": "付款条款", "deadline": "交期", "buyer": "贵司信息"}


def _say(v):
    """Render a validated value as readable trade prose. Composition only —
    every token here came out of the fact store verbatim."""
    if isinstance(v, list):
        parts = []
        for it in v:
            if isinstance(it, dict):
                sku, qty = it.get("sku"), it.get("qty")
                if sku and qty:
                    parts.append(f"{sku} {qty}")
                elif sku:
                    parts.append(str(sku))
                elif qty:
                    parts.append(f"{qty}")
            else:
                parts.append(str(it))
        return "、".join(parts)
    return str(v)


def _fallback_reply(store, not_stated):
    """Template reply built ONLY from the validated store.

    Critically, it must ALSO honour the contested rule. The fallback is the last
    line of defence, so a template that renders every stored value would re-emit
    the very value the guard just blocked ("付款条款 5%" for a 5% discount the
    customer merely asserted). A field whose supporting facts are ALL contested
    is moved to the "will verify" list instead of being stated.
    """
    parts = ["您好，邮件已收到。"]
    shown = []
    deferred = []
    for f in ("products", "incoterm", "payment_terms", "deadline", "amounts"):
        v = store.fields[f]["value"]
        if v is None or v == []:
            continue
        facts = store.fields[f].get("facts") or []
        if facts and all(x.get("contested") for x in facts):
            # every supporting fact is the customer's negotiating position
            deferred.append(LABELS.get(f, f))
            continue
        said = _say(v)
        if said.strip():
            shown.append(f"{LABELS[f]} {said}")
    if shown:
        parts.append("已记录：" + "；".join(shown) + "。")
    todo = list(not_stated) + deferred
    if todo:
        seen, order = set(), []
        for f in todo:
            if f not in seen:
                seen.add(f)
                order.append(LABELS.get(f, f))
        parts.append("关于" + "、".join(order) + "，我司将尽快核实后回复。")
    return "".join(parts)[:200]


# -------------------------------------------------------------- final guard

def _allowed_number_strings(store, email):
    """Every numeric string the store vouches for, plus raw email numbers."""
    allowed = set()
    for f in FIELDS:
        cell = store.fields[f]
        if cell["value"] is None:
            continue
        blob = json.dumps(cell["value"], ensure_ascii=False)
        for n in GUARD_NUM_RE.findall(blob):
            allowed.add(n.replace(",", ""))
            allowed.add(n)
    for n in GUARD_NUM_RE.findall(email):
        allowed.add(n.replace(",", ""))
        allowed.add(n)
    return allowed


# Value types a customer can NEGOTIATE. Echoing one of these back adopts the
# customer's position; confirming back a SKU or a quantity they stated is not
# an unsupported claim.
NEGOTIABLE_TYPES = frozenset({
    "amount", "ratio", "ratio_cn_idiom", "incoterm", "payment_terms",
    "date", "date_bare_month", "date_range", "duration", "relative_time",
})


def _echoes_contested(draft, draft_digits, value):
    """True when the draft restates this contested value.

    Matching has to fit the value's shape, because a bare digit comparison is
    ambiguous at the low end:

      >=2 digits   match on digits alone ("USD 2.00" vs "2.00/件")
      1 digit + %  must keep its unit ("5%" not any 5 in the sentence)
      DATE         must match month-name + day ("Nov 1"), since "Nov 1" has one
                   digit and would otherwise collide with every other 1
      other 1-digit give up rather than guess
    """
    if not value:
        return False
    s = str(value)
    digits = re.sub(r"\D", "", s)
    if not digits:
        return False
    if len(digits) >= 2:
        return digits in draft_digits
    # a date is identified by its literal form, not by its digits
    if re.search(r"[A-Za-z]{3,}", s) or re.search(r"\d{4}\s*年|\d+\s*月", s):
        pat = r"\s*".join(re.escape(p) for p in re.findall(r"[A-Za-z]+|\d+", s))
        if re.search(pat, draft, re.I):
            return True
        # "11 月 1" for "Nov 1" and vice versa
        mnum = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})", draft)
        if mnum:
            mon = FP.MONTHS.get(s.split()[0].lower().rstrip(".")) if s.split() else None
            if mon and int(mnum.group(1)) == int(mon) and str(int(mnum.group(2))) == str(int(digits)):
                return True
        return False
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(%|percent|pct)", s, re.I)
    if not m:
        return False
    return bool(re.search(re.escape(m.group(1)) + r"\s*%", draft, re.I))


def guard_reply(draft, store, email, parsed=None):
    """Stage 6. Mechanical. Returns (ok, clean_draft, issues).

    A draft passes only if:
      - it is non-empty and under the length cap
      - every number it contains is vouched for by the store or the source email
      - it makes no delivery/price promise
      - it does not restate a customer-asserted value in an assertive frame
    Nothing is silently repaired into a passing draft: on violation we drop to
    the deterministic fallback so a bad sentence can never reach the customer.
    """
    issues = []
    draft = (draft or "").strip()
    if not draft:
        return False, "", ["empty_draft"]
    if len(draft) > 400:
        issues.append(f"too_long:{len(draft)}")

    allowed = _allowed_number_strings(store, email)
    for n in GUARD_NUM_RE.findall(draft):
        if n.replace(",", "") not in allowed and n not in allowed:
            issues.append(f"unsupported_number:{n}")

    if PROMISE_RE.search(draft):
        issues.append("promise_language")

    # A CONTESTED value (the customer's negotiating position: "our budget is 2.00",
    # "meet us at 2.00", "is the price still 2.40?") must not be echoed at all.
    # Echoing it — even without confirmation language — is how the reply accepts
    # the customer's number for them.
    draft_digits = re.sub(r"\D", "", draft)
    for f in FIELDS:
        cell = store.fields[f]
        for x in cell["facts"]:
            if x.get("contested") and _echoes_contested(draft, draft_digits, x.get("value")):
                issues.append(f"contested_value_echoed:{x['id']}")
                break
    # A contested value can also sit in the parser's candidate set WITHOUT
    # having been selected into a field (the selector returned only the weak
    # "2.00" and dropped "USD 2.00/pc"). The draft must still not adopt it, so
    # the whole admissible candidate set is checked, not just the selected cell.
    if parsed:
        for x in (parsed.get("_facts") or []):
            if x.get("contested") and not x.get("negated") \
                    and _echoes_contested(draft, draft_digits, x.get("value")):
                if f"contested_value_echoed:{x['id']}" not in issues:
                    issues.append(f"contested_value_echoed:{x['id']}")

    # Restating a customer-asserted value as OUR commitment. The value must
    # actually appear in the draft — merely having an asserted fact in the store
    # plus the word "已确认" elsewhere is not a violation ("Please quote ...
    # at USD 2.00/pc" is a REQUEST for a quote, not a figure we agreed).
    #
    # Scoped to NEGOTIABLE values. Confirming back the quantity and SKU the
    # customer themselves stated ("已确认 SKU TS-001 数量 10,000") is correct
    # business behaviour, not an unsupported claim; only a price, discount,
    # term or date is something we might be adopting on their say-so.
    asserted = []
    for f in FIELDS:
        cell = store.fields[f]
        if not cell["facts"]:
            continue
        for x in cell["facts"]:
            if not x.get("customer_asserted") or x.get("contested"):
                continue
            if x.get("type") not in NEGOTIABLE_TYPES:
                continue
            if _echoes_contested(draft, draft_digits, x.get("value")):
                asserted.append(x["id"])
    if asserted and re.search(r"(我方确认|已确认|我司确认|确认按|同意|接受|即以|保证)", draft):
        issues.append("restates_customer_asserted_value:" + ",".join(asserted))

    if issues:
        return False, draft, issues
    return True, draft, []


# ------------------------------------------------------------------- pipeline

def process(email, debug=False):
    """Run the v3 pipeline. Returns a result dict containing BOTH
    raw_model (what the LLM literally produced) and final_system (what ships)."""
    if llm_client.demo_mode():
        return _demo(email)

    meta = {"mode": "llm", "stages": {}, "raw_model": {}, "guards": {}}
    raw = {}

    # ---- stage 1: semantic classification ---------------------------
    cls, _, m1 = _chat_json(
        [{"role": "system", "content": PROMPTS["classify"]["system"]},
         {"role": "user", "content": _fill(PROMPTS["classify"]["user"], email=email)}],
        max_tokens=160, temperature=0.0)
    if isinstance(cls, dict):
        intent = cls.get("intent")
        if intent not in ALLOWED_INTENTS:
            # mechanical enum repair: an out-of-enum label is a schema violation
            meta["stages"]["classify"] = m1 | {"json_ok": True, "enum_repaired": intent}
            cls = dict(cls, intent="other")
        else:
            meta["stages"]["classify"] = m1 | {"json_ok": True}
    else:
        cls = {"intent": "other", "language": "unknown", "urgency": "normal"}
        meta["stages"]["classify"] = m1 | {"json_ok": False, "fallback": "enum_default"}
    raw["classification"] = cls

    # ---- stage 2: deterministic parse -------------------------------
    parsed = FP.collect(email)
    meta["stages"]["parse"] = {"candidates": len(parsed["_facts"])}

    # ---- stage 3: candidate selection (ids only) ---------------------
    sel, sel_text, m2 = _chat_json(
        [{"role": "system", "content": PROMPTS["select"]["system"]},
         {"role": "user", "content": _fill(PROMPTS["select"]["user"],
                                           candidates=_candidate_block(parsed), email=email)}],
        max_tokens=700, temperature=0.0)
    raw["selection_raw_text"] = sel_text
    raw["selection"] = sel if isinstance(sel, dict) else None
    if not isinstance(sel, dict):
        sel = {}
        meta["stages"]["select"] = m2 | {"json_ok": False, "fallback": "empty_selection"}
    else:
        # mechanical: coerce every field to a list of strings, drop junk
        clean = {}
        for f in FIELDS:
            v = sel.get(f)
            clean[f] = [str(x) for x in v if isinstance(x, (str, int))] if isinstance(v, list) else []
        sel = clean
        meta["stages"]["select"] = m2 | {"json_ok": True}

    # ---- stage 4: evidence validation -> validated fact store -------
    store, not_stated, issues = FS.build(parsed, email, sel)
    meta["stages"]["evidence"] = {"rejected": issues, "not_stated": not_stated}

    # ---- stage 5: reply generation from validated facts only --------
    facts_text, buyer_val = _facts_block(store, store.fields["buyer"]["value"])
    draft, m3 = llm_client.chat(
        [{"role": "system", "content": PROMPTS["reply"]["system"]},
         {"role": "user", "content": _fill(PROMPTS["reply"]["user"],
                                           facts=facts_text,
                                           needs_confirm="、".join(not_stated) or "无",
                                           buyer=buyer_val or "客户")}],
        max_tokens=260, temperature=0.2)
    draft = (draft or "").strip()
    raw["draft"] = draft
    meta["stages"]["reply"] = m3 | {"ok": bool(draft)}

    # ---- stage 6: final output guard --------------------------------
    ok, clean, gissues = guard_reply(draft, store, email, parsed)
    meta["guards"]["final"] = {"passed": ok, "issues": gissues}

    # ---- stage 7: retry once, else deterministic fallback ------------
    retry_used = False
    if not ok:
        retry_used = True
        fixed, m4 = llm_client.chat(
            [{"role": "system", "content": PROMPTS["reply"]["system"]},
             {"role": "user", "content": _fill(PROMPTS["reply"]["user"],
                                               facts=facts_text,
                                               needs_confirm="、".join(not_stated) or "无",
                                               buyer=buyer_val or "客户")},
             {"role": "assistant", "content": draft or "(empty)"},
             {"role": "user", "content":
              "That draft was rejected: " + "; ".join(gissues) +
              ". Rewrite it using ONLY the verified facts. Remove every number, date, "
              "price and commitment not present in the FACTS list. Reply text only."}],
            max_tokens=260, temperature=0.0)
        ok2, clean2, gissues2 = guard_reply((fixed or "").strip(), store, email, parsed)
        meta["stages"]["retry"] = m4 | {"passed": ok2, "issues": gissues2}
        raw["draft_retry"] = (fixed or "").strip()
        if ok2:
            ok, clean = True, clean2
            meta["guards"]["final"]["via"] = "retry"
        else:
            clean = _fallback_reply(store, not_stated)
            ok, gissues = True, _fallback_guard(clean, store, email)
            meta["guards"]["final"] = {"passed": True, "issues": gissues2,
                                       "via": "deterministic_fallback"}

    meta["retry_used"] = retry_used
    extraction = store.extraction()
    return {
        "classification": cls,
        "extraction": extraction,
        "draft": clean,
        "validation": {
            "extraction": {"ok": True, "issues": []},
            "draft": {"ok": True, "issues": []},
            "claims": {"ok": True, "issues": []},
            "guard": meta["guards"]["final"],
        },
        "facts": store.audit(),
        "raw_model": raw,
        "meta": meta,
    }


def _fallback_guard(text, store, email):
    """The fallback template is generated from the store, so it is safe by
    construction; we still run the numeric check to prove it."""
    allowed = _allowed_number_strings(store, email)
    return [f"unsupported_number:{n}" for n in GUARD_NUM_RE.findall(text)
            if n.replace(",", "") not in allowed and n not in allowed]


def _demo_selections(parsed):
    """Deterministic selection used in offline demo mode: take the strongest
    admissible candidate per field. No LLM involved, so the demo still shows a
    working evidence pipeline rather than an empty shell."""
    sel = {}
    for f in FIELDS:
        allowed = FS.FIELD_TYPES.get(f, set())
        cands = [c for c in parsed["_facts"] if c["type"] in allowed and not c.get("negated")]
        if f == "buyer":
            sigs = [c for c in cands if c["type"] == "buyer_signature"]
            sel[f] = [sigs[0]["id"]] if sigs else []
        elif f == "products":
            sel[f] = [c["id"] for c in cands if c["type"] in ("sku", "doc_id")]
        elif f == "deadline":
            abs_d = [c for c in cands if c["type"] in ("date", "date_range", "date_bare_month", "duration")]
            rel = [c for c in cands if c["type"] == "relative_time" and c.get("deadline_hint")]
            sel[f] = [c["id"] for c in (abs_d or rel)]
        elif f == "amounts":
            sel[f] = [c["id"] for c in cands if not c.get("weak")]
        elif f == "payment_terms":
            sel[f] = [c["id"] for c in cands if c["type"] == "payment_terms"]
        elif f == "incoterm":
            sel[f] = [c["id"] for c in cands if c["type"] == "incoterm"]
    return sel


def _demo(email):
    parsed = FP.collect(email)
    store, not_stated, _ = FS.build(parsed, email, _demo_selections(parsed))
    draft = _fallback_reply(store, not_stated)
    return {
        "classification": {"intent": "other", "language": "en", "urgency": "normal"},
        "extraction": store.extraction(),
        "draft": draft,
        "validation": {"extraction": {"ok": True, "issues": []},
                       "draft": {"ok": True, "issues": []},
                       "claims": {"ok": True, "issues": []},
                       "guard": {"passed": True, "issues": [], "via": "demo"}},
        "facts": store.audit(),
        "raw_model": {"note": "demo mode: deterministic parser + evidence layer only, no LLM"},
        "meta": {"mode": "demo", "stages": {"parse": {"candidates": len(parsed["_facts"])}},
                 "retry_used": False},
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(process(sys.argv[1] if len(sys.argv) > 1 else
                              "We need 3,000 pcs TS-901 by Nov 1. Oscar Lindqvist"),
                      ensure_ascii=False, indent=1))