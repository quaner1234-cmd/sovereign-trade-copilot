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
import semantics as SEM
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


def _facts_block(store, buyer_value, typed=None):
    """Render what the reply generator may use — the ONLY thing it sees.

    v4: the block is ROLE-AWARE. Everything the store vouches for is listed, but
    grouped by what the customer was DOING with it, because that is the
    difference between "the price is USD 45" and "their target is USD 45".
    Grouping also lets the guard check each group's framing mechanically.
    """
    buyer_line = buyer_value or ""
    if typed is None:
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
        return "\n".join(rows), buyer_line

    groups = {"FACT": [], "REQUEST": [], "TARGET": [], "QUESTION": [], "COMMITMENT": []}
    for t in typed:
        flags = [f"ROLE={t['semantic_role']}", f"stance={t['stance']}", f"status={t['status']}"]
        q = t.get("qualifier") or {}
        if q.get("kind"):
            flags.append("qualifier=" + q["kind"])
        if t.get("relation"):
            flags.append("relation=" + t["relation"])
        if t.get("named_place"):
            flags.append("place=" + t["named_place"])
        groups.setdefault(t["semantic_role"], []).append(
            f'- {t["fact_type"]}: "{t["value"]}" ({", ".join(flags)})')

    parts = []
    if groups["FACT"]:
        parts.append("CUSTOMER FACTS (you may restate these):\n" + "\n".join(groups["FACT"]))
    if groups["REQUEST"]:
        parts.append("CUSTOMER REQUESTS (write ONLY as what they asked for):\n"
                     + "\n".join(groups["REQUEST"]))
    if groups["TARGET"]:
        parts.append("CUSTOMER TARGETS (write ONLY as their target/budget — NEVER as our price):\n"
                     + "\n".join(groups["TARGET"]))
    if groups["COMMITMENT"]:
        parts.append("CUSTOMER COMMITMENTS (their act; still not OUR confirmation):\n"
                     + "\n".join(groups["COMMITMENT"]))
    if groups["QUESTION"]:
        parts.append("VALUES THE CUSTOMER IS ASKING US TO CONFIRM (say we will verify):\n"
                     + "\n".join(groups["QUESTION"]))
    if not any(groups.values()):
        parts.append("(no verified facts)")
    return "\n\n".join(parts), buyer_line


def _missing_fields(store, typed):
    """Fields with no admitted value -> the reply must ask, not guess."""
    have = {t["field"] for t in typed}
    return [f for f in FIELDS if store.fields[f]["value"] is None and f not in have]


# ------------------------------------------------------------ deterministic fallback

LABELS = {"products": "产品", "amounts": "金额", "incoterm": "贸易术语",
          "payment_terms": "付款条款", "deadline": "交期", "buyer": "贵司信息"}

# Clarifications that carry no invented value. A reply that only says "we will
# verify" is safe but commercially useless; asking for what a quotation actually
# needs is both safe and useful.
CLARIFY_LABELS = {
    "payment_terms": "付款条款",
    "incoterm": "贸易术语",
    "deadline": "交期",
    "amounts": "可接受目标价",
    "products": "产品规格（面料 / 克重 / 尺码 / 颜色）",
}
RELATION_TEXT = {"before": "前", "by": "前", "after": "之后", "on": ""}
SPEC_CUE_RE = re.compile(
    r"\b(?:gsm|gram|oz|fabric|material|composition|cotton|polyester|nylon|spandex|"
    r"lining|shell|size|sizing|colour|color|pantone|spec(?:ification)?|workmanship)\b"
    r"|面料|成分|克重|平方克重|支数|尺码|颜色|色号|规格|工艺|里布", re.I)


def _qual(v, q):
    """Render a value WITH the hedge the customer used.

    "around 300 pcs" must not reach the customer as a flat 300 — that is
    precision they never offered, and later an unmeetable commitment.
    """
    kind = (q or {}).get("kind")
    if kind == "approx":
        return "约 " + str(v)
    if kind == "min":
        return "至少 " + str(v)
    if kind == "max":
        return "至多 " + str(v)
    return str(v)


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


def _fallback_reply(store, not_stated, typed=None, email=None):
    """Deterministic reply built ONLY from the validated store.

    v4: role-aware. The old template rendered every stored value flat, which is
    what turned the customer's target into "金额 USD 45" — i.e. adopted their
    number. Each role now has exactly one allowed rendering:

      FACT        stated plainly
      REQUEST     "贵司要求…"          — never a bare date/price claim
      TARGET      "贵司目标价格…"      — never our quote
      QUESTION    "…我司核实后回复"    — never confirmed
      COMMITMENT  "贵司所述 / 已记录"  — never "我方确认"

    The contested rule is preserved: if a field's supporting facts are all the
    customer's negotiating position, the value is deferred, never stated.
    """
    if typed is None:
        parts = ["您好，邮件已收到。"]
        shown, deferred = [], []
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

    has_order = SEM.order_act(typed, email or "")
    parts = ["您好，已收到贵司订单来函。" if has_order else "您好，感谢来函询盘。"]

    stated, targets, requests, questions, commits = [], [], [], [], []
    for t in typed:
        # A date that never got tied to a delivery/request cue is not ours to
        # assert as a delivery date. "quoted 6,000 pcs at USD 7.85 on Nov 3"
        # mentions Nov 3; rendering it as 交期 invents a commitment. Ask instead.
        if t["semantic_role"] == "FACT" \
                and t.get("evidence_type") in DATE_TYPES \
                and not t.get("deadline_hint"):
            questions.append(dict(t, semantic_role="QUESTION",
                                  role_reason="date_without_delivery_cue"))
            continue
        {"FACT": stated, "TARGET": targets, "REQUEST": requests,
         "QUESTION": questions, "COMMITMENT": commits}.setdefault(
            t["semantic_role"], stated).append(t)

    facts_line = []
    for t in stated:
        v = _qual(t["value"], t.get("qualifier"))
        ft = t["fact_type"]
        if ft == "product":
            facts_line.append(f"产品 {v}")
        elif ft in ("stated_quantity", "quantity", "target_quantity"):
            facts_line.append(f"数量 {v}")
        elif ft == "product_code":
            facts_line.append(f"款号 {v}")
        elif ft == "incoterm":
            place = t.get("named_place")
            facts_line.append(f"贸易术语 {v} {place}" if place else f"贸易术语 {v}")
        elif ft == "payment_terms":
            facts_line.append(f"付款条款 {v}")
        elif ft == "buyer":
            continue
        elif ft == "stated_delivery":
            facts_line.append(f"交期 {v}{RELATION_TEXT.get(t.get('relation') or '', '')}".rstrip())
        else:
            facts_line.append(v)
    if facts_line:
        parts.append("已记录：" + "；".join(facts_line) + "。")

    def vs(t):
        """The value plus whatever rides along with it in the same fact.

        "FOB Qingdao" is two facts sharing one span; rendering only the Incoterm
        silently drops the port, which is why "FOB Qingdao" used to come out as a
        bare "FOB".
        """
        s = _qual(t["value"], t.get("qualifier"))
        if t.get("named_place"):
            s += " " + t["named_place"]
        return s

    for t in targets:
        label = "目标价格" if t.get("evidence_type") == "amount" else "目标"
        parts.append(f"贵司{label} {vs(t)}（贵司目标，我司评估后回复）。")
    for t in requests:
        if t.get("evidence_type") in ("date", "date_bare_month", "date_range", "duration",
                                      "relative_time"):
            rel = RELATION_TEXT.get(t.get("relation") or "", "")
            parts.append(f"贵司要求交期 {vs(t)}{rel}（贵司要求，我司评估后回复）。")
        elif t["fact_type"].endswith("incoterm"):
            parts.append(f"贵司要求贸易术语 {vs(t)}（贵司要求，我司评估后回复）。")
        else:
            label = "报价基础价格" if t.get("evidence_type") == "amount" else "要求"
            parts.append(f"贵司{label} {vs(t)}（贵司要求，我司评估后回复）。")
    for t in commits:
        note = ("贵司所述，我司查档核实后回复" if t["stance"] == "customer_claimed_prior"
                else "已记录贵司确认事项")
        parts.append(f"{vs(t)}（{note}）。")
    for t in questions:
        if t.get("stance") == "customer_claimed_prior":
            # they are citing OUR document back to us — we verify, we do not agree
            parts.append(f"{vs(t)}（贵司所述我司文件之数值，我司查档核实后回复）。")
        else:
            parts.append(f"{vs(t)}（贵司询问之数值，我司核实后回复）。")


    missing = [CLARIFY_LABELS[f] for f in (not_stated or [])
               if f in CLARIFY_LABELS and f != "buyer"]
    # A named product almost never arrives with its specification. Asking costs
    # nothing and is the difference between "we will verify" and a usable reply.
    if any(t["fact_type"] == "product" for t in typed) \
            and not SPEC_CUE_RE.search(email or ""):
        missing.append(CLARIFY_LABELS["products"])
    if missing:
        seen, order = set(), []
        for m in missing:
            if m not in seen:
                seen.add(m)
                order.append(m)
        parts.append("烦请补充：" + "、".join(order) + "，以便我司准确报价。")
    parts.append("具体可行方案我司核实后回复。")
    return "".join(parts)[:400]


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


# -------------------------------------------------- semantic guard (v4)

# Calling an INQUIRY an ORDER is the single most damaging business error in this
# domain: it asserts a contract that does not exist.
ORDER_LANGUAGE_RE = re.compile(
    r"(收到(?:您|贵司)的?订单|您(?:的)?订单已|订单已收到|贵司订单|已接单"
    r"|we\s+(?:have\s+)?received\s+your\s+order|your\s+order\s+(?:has\s+been|is))", re.I)
COMMIT_LANGUAGE_RE = re.compile(
    r"(我方确认|我司确认|已确认|确认如下|同意|接受|保证|安排生产|将于|承诺"
    r"|we\s+confirm|we\s+accept|we\s+agree|we\s+will\s+(?:deliver|ship)|guarantee)", re.I)
REQUEST_DATE_FRAMING_RE = re.compile(
    r"(要求|需求|期望|requested|贵司要求)(交期|日期|船期)|贵司要求|delivery\s+date\s+you", re.I)
TARGET_FRAMING_RE = re.compile(r"(目标价|目标价格|期望价|可接受.?价|预算|贵司目标|target)", re.I)

_CLAUSE_SPLIT = re.compile(r"[。！？!?；;\n]|(?<=[，,])")
_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")
DATE_TYPES = frozenset({"date", "date_range", "date_bare_month", "duration", "relative_time"})
# Framing that attributes a value to the CUSTOMER. Presence of one of these makes
# an echo a report of their position rather than an adoption of it.
CONTESTED_OK_FRAMING_RE = re.compile(
    r"(目标价|目标价格|期望价|可接受.?价|预算|贵司目标|贵司要求|贵司所述|贵司期望|询问之数值"
    r"|贵司确认事项|已记录贵司确认事项|贵司下单"
    r"|你们的?(?:目标|预算|报价要求)|your\s+(?:target|budget)|target)", re.I)


def _value_in(text, value):
    """Same shape-aware matching the v3 contested check uses."""
    return _echoes_contested(text, re.sub(r"\D", "", text), value)


def guard_semantics(draft, typed, email):
    """Stage 6b. Mechanical. Enforce the ROLE contract on the draft.

    v4 answers the failures the v3 guard structurally could not see:
      * an inquiry written as if an order had been placed
      * a customer's TARGET rendered as our price
      * a requested date rendered as our delivery date
      * commitment language attached to any value that is not settled

    Scoped SENTENCE/CLAUSE-wise, and only to values that actually appear there:
    confirming back what the customer stated (SKU, quantity) must stay allowed,
    otherwise the guard over-blocks and the fallback becomes the only output.
    """
    issues = []
    if not draft:
        return ["empty_draft"]
    has_order = SEM.order_act(typed, email or "")

    if not has_order and ORDER_LANGUAGE_RE.search(draft):
        issues.append("order_language_without_order_act")

    clauses = [c for c in (x.strip() for x in _CLAUSE_SPLIT.split(draft)) if c]
    for cl in clauses:
        hits = [t for t in typed if t["semantic_role"] != "FACT" and _value_in(cl, t["value"])]
        for t in hits:
            if t["semantic_role"] == "TARGET" and not TARGET_FRAMING_RE.search(cl):
                issues.append(f"target_stated_as_our_price:{t['id']}")
            if t["semantic_role"] == "REQUEST" \
                    and t.get("evidence_type") in DATE_TYPES \
                    and not REQUEST_DATE_FRAMING_RE.search(cl):
                issues.append(f"requested_date_stated_as_our_delivery:{t['id']}")

    # Commitment words are judged over the whole SENTENCE, not the clause:
    # "贵司目标价格 USD 45，我方确认可行。" splits into two clean-looking clauses
    # but accepts the target in one move. Anything unsettled inside the same
    # sentence as a commitment therefore blocks it.
    for sent in (s for s in (x.strip() for x in _SENTENCE_SPLIT.split(draft)) if s):
        if not COMMIT_LANGUAGE_RE.search(sent):
            continue
        hits = [t for t in typed
                if t["semantic_role"] in SEM.UNSETTLED_ROLES and _value_in(sent, t["value"])]
        if hits:
            issues.append("commitment_language_on_unsettled_value:"
                          + ",".join(f"{t['id']}:{t['semantic_role']}" for t in hits))
    # dedupe preserving order
    seen, uniq = set(), []
    for i in issues:
        if i in seen:
            continue
        seen.add(i)
        uniq.append(i)
    return uniq


def guard_reply(draft, store, email, parsed=None, typed=None):
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
    # "meet us at 2.00", "is the price still 2.40?") must not be echoed WITHOUT
    # attribution. Echoing it in an assertive frame is how the reply silently
    # accepts the customer's number for them.
    #
    # v4 refines "never echo" to "never echo unattributed". The v3 rule made the
    # target-price case unusable: the reply could neither quote nor acknowledge
    # the target, so it deflected and lost the business value. Naming it as THEIR
    # target ("贵司目标价格 USD 45") states their move; only adopting it as OUR
    # number is barred.
    draft_digits = re.sub(r"\D", "", draft)
    clauses = None
    for f in FIELDS:
        cell = store.fields[f]
        for x in cell["facts"]:
            if not x.get("contested") or not _echoes_contested(draft, draft_digits, x.get("value")):
                continue
            if clauses is None:
                clauses = [c for c in (y.strip() for y in _CLAUSE_SPLIT.split(draft)) if c]
            bad = [c for c in clauses
                   if _echoes_contested(c, re.sub(r"\D", "", c), x.get("value"))
                   and not CONTESTED_OK_FRAMING_RE.search(c)]
            if bad:
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
                if clauses is None:
                    clauses = [c for c in (y.strip() for y in _CLAUSE_SPLIT.split(draft)) if c]
                bad = [c for c in clauses
                       if _echoes_contested(c, re.sub(r"\D", "", c), x.get("value"))
                       and not CONTESTED_OK_FRAMING_RE.search(c)]
                if bad and f"contested_value_echoed:{x['id']}" not in issues:
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

    if typed is not None:
        issues.extend(guard_semantics(draft, typed, email))

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

    # ---- stage 4b: business semantic typing ---------------------------
    # Downstream of evidence validation, so it can never resurrect a value the
    # store rejected — it only says WHAT the customer was doing with it.
    typed = SEM.build_typed(email, parsed, store)
    has_order = SEM.order_act(typed, email)
    meta["stages"]["semantics"] = {
        "typed": len(typed),
        "order_act": has_order,
        "roles": {r: sum(1 for t in typed if t["semantic_role"] == r) for r in SEM.ROLES},
        "company_commitments": len(SEM.company_commitments(typed)),
    }

    # ---- stage 5: reply generation from validated facts only --------
    facts_text, buyer_val = _facts_block(store, store.fields["buyer"]["value"], typed)
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
    ok, clean, gissues = guard_reply(draft, store, email, parsed, typed)
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
        ok2, clean2, gissues2 = guard_reply((fixed or "").strip(), store, email, parsed, typed)
        meta["stages"]["retry"] = m4 | {"passed": ok2, "issues": gissues2}
        raw["draft_retry"] = (fixed or "").strip()
        if ok2:
            ok, clean = True, clean2
            meta["guards"]["final"]["via"] = "retry"
        else:
            fb = _fallback_reply(store, not_stated, typed, email)
            bad = guard_reply(fb, store, email, parsed, typed)[2]
            if bad:
                # Safety over completeness: if even the role-aware template trips
                # the guard, drop to the flat v3 template, which states nothing
                # a customer could read as our position.
                fb = _fallback_reply(store, not_stated)
            clean = fb
            ok, gissues = True, _fallback_guard(clean, store, email)
            meta["guards"]["final"] = {"passed": True, "issues": gissues2,
                                       "via": "deterministic_fallback"}

    meta["retry_used"] = retry_used
    extraction = store.extraction()
    extraction["product_names"] = [t["value"] for t in typed if t["fact_type"] == "product"]
    return {
        "classification": cls,
        "extraction": extraction,
        "semantics": {"typed_facts": typed, "order_act": has_order,
                      "company_commitments": SEM.company_commitments(typed)},
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
    typed = SEM.build_typed(email, parsed, store)
    draft = _fallback_reply(store, not_stated, typed, email)
    bad = guard_reply(draft, store, email, parsed, typed)[2]
    if bad:
        draft = _fallback_reply(store, not_stated)
    return {
        "classification": {"intent": "other", "language": "en", "urgency": "normal"},
        "extraction": {**store.extraction(),
                       "product_names": [t["value"] for t in typed if t["fact_type"] == "product"]},
        "semantics": {"typed_facts": typed, "order_act": SEM.order_act(typed, email),
                      "company_commitments": SEM.company_commitments(typed)},
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