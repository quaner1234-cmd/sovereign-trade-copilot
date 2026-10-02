# -*- coding: utf-8 -*-
"""Business semantic layer (v4) — what the customer SAID vs ASKED vs TARGETED.

The v3 evidence layer answers only "is this value evidenced?". That is not
enough to write a safe reply: `supported` says the customer said USD 45, but not
whether it is OUR price, THEIR target, or a price they are asking us to confirm.
Echoing a target as our quote is how the system accidentally accepts terms.

This module types every validated fact along three independent axes:

  semantic_role  FACT | REQUEST | TARGET | QUESTION | COMMITMENT | UNKNOWN
                 what speech act the value performs
  stance         customer | customer_claimed_prior | company | unattributed
                 WHOSE position it is. In an INBOUND email the first person is
                 the customer, so "we agreed / we confirm" is the customer's own
                 stance — never ours.
  status         supported | unconfirmed | not_stated
                 whether it is settled business fact. Anything the customer is
                 pushing for is unconfirmed by construction.

Design rules kept deliberately narrow so the layer generalises:
  * assignment is by SPEECH-ACT CUE CLASS, never by literal string from one email
  * ambiguity always downgrades toward the less committal role
  * only NEGOTIABLE types get a non-FACT role; a signature or a style code is a
    fact whoever writes it
  * the LLM never assigns a role and can never upgrade one — it is given the
    role as constraint text
"""
import re

# ---------------------------------------------------------------- enums

ROLES = ("FACT", "REQUEST", "TARGET", "QUESTION", "COMMITMENT", "UNKNOWN")
STANCES = ("customer", "customer_claimed_prior", "company", "unattributed")
STATUSES = ("supported", "unconfirmed", "not_stated")

# Roles that do NOT authorise commitment language ("已确认/we will deliver").
UNSETTLED_ROLES = ("REQUEST", "TARGET", "QUESTION")

# Only these fact types can be the object of a negotiation position.
SEMANTIC_TYPES = {"amount", "ratio", "ratio_cn_idiom", "qty", "date", "date_range",
                  "date_bare_month", "duration", "relative_time", "incoterm",
                  "payment_terms", "relative_time"}
# An interrogative sentence questions whether a PRICE or a DATE still holds. It
# does not unset an Incoterm: "Could you quote FOB Qingdao?" names the requested
# basis; it does not ask whether FOB is in force.
QUESTIONABLE_TYPES = {"amount", "ratio", "ratio_cn_idiom", "date", "date_range",
                      "date_bare_month", "duration", "relative_time"}

# ---------------------------------------------------------------- cue classes

# A price/target GOAL the customer wants us to reach.
TARGET_CUE = re.compile(
    r"(?:our|the|my)\s+(?:target|budget|aim|cap)\b"
    r"|target\s+(?:price|cost|landed)\b"
    r"|price\s+(?:target|cap|ceiling)\b"
    r"|aim(?:ing)?\s+(?:at|for)\b"
    r"|we\s+(?:can\s+only|need\s+to\s+be|have\s+to\s+be|must\s+be)\s+(?:at|under|below|around)\b"
    r"|we\s+can\s+only\s+(?:pay|accept|do)\b"
    r"|we\s+need\s+(?:it\s+)?(?:at|under|below)\b"
    r"|would\s+like\s+(?:to\s+be\s+)?(?:at|under)\b"
    r"|目标价|预算|期望价|目标价位|希望能到|可接受价格",
    re.I)

# The customer wants something FROM us.
REQUEST_CUE = re.compile(
    r"\bwe\s+(?:need|require|want|would\s+like|wish)\b"
    r"|\bplease\s+(?:quote|send|advise|provide|arrange|ship|deliver|confirm|issue)\b"
    r"|\bkindly\s+(?:quote|send|advise|provide)\b"
    r"|\bwe\s+ask\b|\brequest(?:ed|ing)?\b"
    r"|\bwe\s+must\s+(?:receive|get|have)\b"
    r"|\bmust\s+(?:arrive|be\s+(?:delivered|shipped|ready)|ship)\b"
    # imperative delivery instruction: "Deliver the sleeping bags by Oct 3",
    # "Dispatch 2,000 pcs to Hamburg". Asking us to deliver IS a request.
    r"|(?:^|[.!?;]\s|\n\s*)\s*(?:please\s+)?(?:deliver|dispatch|ship)\s+(?:the|our|all|\d)"
    r"|我们需要|请报价|请提供|请安排|请发货|需用|要有|须在|务必|交货至|发货至",
    re.I)

# The customer is asking whether a value still holds / asking us to confirm it.
QUESTION_CUE = re.compile(
    r"\bis\s+(?:the|that|it)\b|\bare\s+(?:the|those|these)\b"
    r"|\bstill\s+(?:valid|available|open|possible|correct)\b"
    r"|\bcan\s+you\s+(?:confirm|advise|check|still)\b"
    r"|\bcould\s+you\s+(?:confirm|advise|check|please)\b"
    r"|\bplease\s+(?:confirm|advise|check|verify)\b"
    r"|\blet\s+us\s+know\b|\bcorrect\?|\bright\?|\btrue\?\b"
    r"|是否|还有效吗|对吗|麻烦确认|能否确认|请确认是否",
    re.I)

# The customer commits to something. In an inbound mail this is THEIR act.
COMMIT_CUE = re.compile(
    r"\bwe\s+(?:confirm|accept|agree|agreed|have\s+agreed|hereby\s+order|will\s+order|place)\b"
    r"|\bwe\s+(?:take|will\s+take)\b"
    r"|\bPO\b[^.\n]{0,14}?\bis\s+confirmed\b|\border\s+(?:is\s+)?confirmed\b"
    r"|\bplease\s+proceed\b|\bpleased\s+to\s+place\b"
    r"|\bwe\s+have\s+decided\s+to\s+order\b"
    r"|我们确认|我司确认(?:订购)?|我们接受|我方下单|确认下单|请安排生产|订单确认",
    re.I)
# A commitment that points BACKWARD is a claim about a past agreement, not a
# live act: it cannot be treated as settled even though it uses the same verbs.
PRIOR_CUE = re.compile(
    r"\blast\s+(?:year|season|month|week|time)\b|\bpreviously\b|\bearlier\b"
    r"|\boriginally\b|\bin\s+(?:19|20)\d\d\b|\bper\s+(?:our|the)\s+(?:last|previous)\b"
    r"|\bas\s+(?:agreed|confirmed)\s+(?:last|previously|earlier)\b"
    r"|去年|上次|原先|之前的约定|历史",
    re.I)
# NOTE: a bare "before" is NOT a past reference — "shipment before Mar 1" is a
# live requirement, not a recollection. Keeping the bare word here turned every
# order with a "before <date>" clause into a claim about the past.

# The ORDER speech act: a genuine order, not interest in one. Requires BOTH a
# document anchor (PO/PI number) and a live commitment verb, in non-prior,
# non-hypothetical framing. An anchor alone is not an order (case: "do not send
# the PI yet"), and neither is "we agreed last month" without an anchor.
ORDER_ACT_CUE = re.compile(
    r"\bPO[- ]?(?:no\.?\s*)?\d|\bPI\b|\bSO[- ]?\d|\bpurchase\s+order\b"
    r"|\border\s+(?:no\.?|number)\b|\bplease\s+proceed\b"
    r"|\bwe\s+(?:hereby\s+)?(?:order|place)\b|\bpurchase\s+order\b"
    r"|订单号|采购订单|确认下单|已下单",
    re.I)
HYPOTHETICAL_CUE = re.compile(
    r"\b(?:initial|first)\s+order\s+(?:would|will|could|should|might)\b"
    r"|\bwould\s+be\b|\bcould\s+be\b|\bif\s+(?:approved|ok|accepted|confirmed)\b"
    r"|\bshould\s+it\s+work\b|\bnext\s+time\b|\bin\s+the\s+future\b"
    r"|\binterested\s+in\b|\benquir(?:e|y|ing)\b"
    r"|有意向|初步意向|如果(?:合作|顺利)",
    re.I)

_SENT_SPLIT = re.compile(r"(?<=[.。!！?？;；])\s+|\n+")
_DECIMAL_PROTECT = re.compile(r"(\d)\.(\d)")


def sentences(email):
    """Sentence split that does NOT break inside decimals.

    A naive split on "." turns "USD 18.50/pc. Volume would be 3,000 pcs." into
    three sentences, which lets a target-price cue leak across the (false)
    boundary onto the next value. Decimals are protected before splitting.
    """
    prot = _DECIMAL_PROTECT.sub(lambda m: m.group(1) + "\u0000" + m.group(2), email)
    return [p.replace("\u0000", ".").strip()
            for p in _SENT_SPLIT.split(prot) if p.strip()]


def sentence_of(email, start):
    pos = 0
    for s in sentences(email):
        nxt = email.find(s, pos)
        if nxt == -1:
            return s
        if nxt <= start < nxt + len(s):
            return s
        pos = nxt + 1
    return email


def _clause_before(email, start, width=45):
    win = email[max(0, start - width):start]
    # "." IS a boundary here. Without it the window walks across a sentence end
    # and a target cue belonging to one value binds the next one.
    cut = max(win.rfind(x) for x in (";", ":", "。", "！", "？", "!", "?", "\n",
                                     ",", "，", ".", ";"))
    if cut != -1:
        win = win[cut + 1:]
    return win


# A value the customer attributes to OUR OWN document: "you quoted 6,000 pcs at
# USD 7.85", "your invoice shows USD 2.30". We cannot confirm it from an inbound
# email — there is no internal record behind it — so it is a claim to verify, not
# a fact and certainly not a commitment.
OUR_DOC_CUE = re.compile(
    r"\byou\s+(?:quoted|offered|priced|invoiced|confirmed|advised|stated)\b"
    r"|\byour\s+(?:quote|quotation|offer|invoice|inv\.|PI|proforma|list\s+price)\b"
    r"|\baccording\s+to\s+your\b|\bas\s+per\s+your\b"
    r"|贵司(?:报价|发票|形式发票|PI|报价单)|你方(?:报价|发票)|贵司清单价",
    re.I)

# ---------------------------------------------------------------- role assignment

def classify(email, fact):
    """Return (semantic_role, stance, reason) for one parser candidate.

    Monotone and fail-safe: the more committal a role is, the more specific a cue
    it needs. Anything unrecognised stays FACT-with-no-commitment-value, which is
    the one outcome that can never over-claim.
    """
    if fact["type"] not in SEMANTIC_TYPES:
        return "FACT", "customer", "non_negotiable_type"
    start = fact["span_start"]
    before = _clause_before(email, start)
    sent = sentence_of(email, start)

    if TARGET_CUE.search(before):
        # Clause-scoped on purpose. A target cue anywhere in the SENTENCE would
        # swallow every number in it ("our budget is 2.00 for the 10,000 pcs JK-220"
        # describes the price; the 10,000 is a stated fact).
        return "TARGET", "customer", "target_cue"

    if fact["type"] in QUESTIONABLE_TYPES and (OUR_DOC_CUE.search(before)
                                               or OUR_DOC_CUE.search(sent)):
        return "QUESTION", "customer_claimed_prior", "cites_our_document"

    if COMMIT_CUE.search(before) or COMMIT_CUE.search(sent):
        stance = "customer_claimed_prior" if PRIOR_CUE.search(sent) else "customer"
        return "COMMITMENT", stance, "commit_cue" + ("+prior" if stance != "customer" else "")

    if REQUEST_CUE.search(before) or REQUEST_CUE.search(sent):
        return "REQUEST", "customer", "request_cue"

    if fact["type"] in QUESTIONABLE_TYPES and (
            QUESTION_CUE.search(before) or QUESTION_CUE.search(sent) or "?" in sent or "？" in sent):
        return "QUESTION", "customer", "question_cue"

    return "FACT", "customer", "no_cue"


# ---------------------------------------------------------------- typed facts

TYPE_TO_FIELD = {
    "amount": "amounts", "ratio": "payment_terms", "ratio_cn_idiom": "payment_terms",
    "qty": "quantity", "date": "deadline", "date_range": "deadline",
    "date_bare_month": "deadline", "duration": "deadline", "relative_time": "deadline",
    "incoterm": "incoterm", "payment_terms": "payment_terms",
    "sku": "product_code", "doc_id": "product_code",
    "buyer_signature": "buyer", "product_name": "product",
}

# A newspeak-free business name for each (semantic_role, base field) pair. The
# reply is generated from these, never from raw values, so the SAME number cannot
# be rendered both as our quote and as their target.
FIELD_NAMES = {
    ("TARGET", "amounts"): "target_price",
    ("QUESTION", "amounts"): "price_to_confirm",
    ("COMMITMENT", "amounts"): "agreed_price_claimed",
    ("REQUEST", "amounts"): "requested_price",
    ("FACT", "amounts"): "quoted_price",
    ("TARGET", "deadline"): "target_delivery",
    ("REQUEST", "deadline"): "requested_delivery",
    ("COMMITMENT", "deadline"): "committed_delivery",
    ("QUESTION", "deadline"): "delivery_to_confirm",
    ("FACT", "deadline"): "stated_delivery",
    ("TARGET", "quantity"): "target_quantity",
    ("REQUEST", "quantity"): "requested_quantity",
    ("COMMITMENT", "quantity"): "committed_quantity",
    ("FACT", "quantity"): "stated_quantity",
    ("TARGET", "incoterm"): "requested_incoterm",
    ("REQUEST", "incoterm"): "requested_incoterm",
    ("COMMITMENT", "incoterm"): "agreed_incoterm_claimed",
    ("FACT", "incoterm"): "incoterm",
    ("TARGET", "payment_terms"): "requested_payment_terms",
    ("REQUEST", "payment_terms"): "requested_payment_terms",
    ("COMMITMENT", "payment_terms"): "agreed_payment_terms_claimed",
    ("FACT", "payment_terms"): "payment_terms",
}


def fact_type_for(field, role):
    return FIELD_NAMES.get((role, field), field)


def build_typed(email, parsed, store):
    """Typed facts built FROM THE VALIDATED STORE, not from the raw candidate set.

    Layering matters: the semantic layer is downstream of evidence validation, so
    it can never resurrect a value the store rejected.
    """
    admitted = {}
    for fname in store.fields:
        for x in (store.fields[fname].get("facts") or []):
            admitted[x["id"]] = fname

    by_id = {f["id"]: f for f in parsed["_facts"]}
    out = []
    for cid, fname in sorted(admitted.items(), key=lambda kv: by_id[kv[0]]["span_start"]):
        f = by_id[cid]
        role, stance, why = classify(email, f)
        # A quantity only ever appears inside the products cell; at the semantic
        # level it is its own business field.
        base = "quantity" if f["type"] == "qty" else TYPE_TO_FIELD.get(f["type"], fname)
        status = "supported" if role == "FACT" else "unconfirmed"
        qual = f.get("qualifier") or {"kind": None, "raw": None, "approx": False}
        rec = {
            "id": f["id"],
            "field": fname,
            "value": f["value"],
            "semantic_role": role,
            "stance": stance,
            "qualifier": qual,
            "status": status,
            "source_span": f["source_span"],
            "span": [f["span_start"], f["span_end"]],
            "fact_type": fact_type_for(base, role),
            "evidence_type": f["type"],
            "role_reason": why,
        }
        if f["type"] == "incoterm" and f.get("named_place"):
            rec["named_place"] = f["named_place"]
        if f.get("relation"):
            rec["relation"] = f["relation"]
        if f.get("number"):
            rec["number"] = f["number"]
        if f.get("unit"):
            rec["unit"] = f["unit"]
        if f["type"] in ("date", "date_range", "date_bare_month", "duration", "relative_time"):
            rec["deadline_hint"] = bool(f.get("deadline_hint"))
        out.append(rec)

    # merchandise named with a common noun — evidence-gated by the same rule
    for pn in (parsed.get("_product_names") or []):
        if pn["source_span"] not in email:
            continue
        out.append({
            "id": "pn" + str(pn["span_start"]),
            "field": "products",
            "value": pn["value"],
            "semantic_role": "FACT",
            "stance": "customer",
            "qualifier": {"kind": None, "raw": None, "approx": False},
            "status": "supported",
            "source_span": pn["source_span"],
            "span": [pn["span_start"], pn["span_end"]],
            "fact_type": "product",
            "evidence_type": "product_name",
            "raw_field": "products",
            "role_reason": "named_merchandise",
        })

    _resolve_cross_sentence_questions(email, out)
    out.sort(key=lambda r: r["span"][0])
    return out


# A question can target a value stated in an EARLIER sentence instead of
# restating it:
#   "You quoted 6,000 pcs RS-204 at USD 7.85 on Nov 3. Is that still valid?"
# The question is about the PRICE; reading sentences in isolation classifies it
# as a settled fact, which is exactly how a reply ends up confirming a number
# the customer was querying.
ANAPHOR_RE = re.compile(
    r"\b(?:that|it|this|those|these|the\s+(?:same|above|price|rate|figure|date))\b"
    r"|是否如此|这个价格|该价格|该日期", re.I)
QUESTIONABLE_FIELD = {"amounts", "payment_terms"}


def _resolve_cross_sentence_questions(email, recs):
    """Re-target MONEY values asked about anaphorically by a FOLLOWING sentence.

    Restricted to monetary values on purpose. Resolving "that" to whichever value
    sits nearest is unreliable — in "quoted at USD 7.85 on Nov 3. Is that still
    valid for a December shipment?" the nearest value is the DATE, but "that"
    refers to the PRICE. Money is the one referent this rule gets right, and a
    wrong date re-labelling would silently invent an unconfirmed delivery date.

    Only fires when the asking sentence carries no monetary value of its own.
    """
    # An explicit local cue (REQUEST, TARGET) always wins over a cross-sentence
    # question reference: "must arrive no later than Dec 5. Please confirm." is a
    # hard requirement they want confirmed, not an open question.
    negotiable = [r for r in recs
                  if r["semantic_role"] == "FACT"
                  and r["field"] in QUESTIONABLE_FIELD]
    prior_cache = None
    for sent in sentences(email):
        if not (QUESTION_CUE.search(sent) and ANAPHOR_RE.search(sent)):
            continue
        pos = email.find(sent)
        prior_cache = [r for r in negotiable if r["span"][0] < pos] or prior_cache
        if not prior_cache:
            continue
        target = max(prior_cache, key=lambda r: r["span"][0])
        # Skip only when the asking sentence already carries a value of the SAME
        # kind — that value, not the earlier one, is what is being asked about.
        # "Is that still valid for a December shipment?" asks about the PRICE even
        # though it mentions December, so a different field does not block it.
        if any(r["field"] == target["field"] and r["source_span"] in sent for r in recs):
            continue
        target["semantic_role"] = "QUESTION"
        target["status"] = "unconfirmed"
        target["role_reason"] = "cross_sentence_question"
        base = "quantity" if target["evidence_type"] == "qty" else target["field"]
        target["fact_type"] = fact_type_for(base, "QUESTION")


# -- derived views ---------------------------------------------------------

def order_act(typed, email):
    """Is there a genuine ORDER act in this email?

    INQUIRY vs ORDER is the distinction that made the old model write "已收到您
    的订单" to someone who had only asked for a quote. Two things must hold and
    one must NOT:
      + a document anchor — a PO/PI number or "purchase order"
      + a LIVE commitment verb somewhere ("we confirm", "please proceed")
      - not framed as past ("last month") or hypothetical ("would be")
    Neither condition alone is sufficient, and neither is the presence of an
    order-like word inside another speech act ("the 1,500 pcs order you quoted").
    """
    sents = sentences(email)
    anchor = any(ORDER_ACT_CUE.search(s) for s in sents)
    if not anchor:
        return False
    for s in sents:
        if PRIOR_CUE.search(s) or HYPOTHETICAL_CUE.search(s):
            continue
        if COMMIT_CUE.search(s):
            return True
    return False


def unconfirmed_items(typed):
    return [t for t in typed if t["status"] == "unconfirmed"]


def company_commitments(typed):
    """Company commitments the reply is allowed to lean on.

    For an inbound customer email this is expected to be EMPTY, and that is the
    point: a first-person commitment in a customer's mail is the customer's own
    stance. Anything the customer claims about us is customer_claimed_prior,
    never company.
    """
    return [t for t in typed if t["stance"] == "company" and t["semantic_role"] == "COMMITMENT"]


def unknown_fields(store_fields, typed, FIELDS):
    """Fields with no admitted value -> UNKNOWN, used to ask clarifying questions."""
    have = {t["field"] for t in typed}
    return [f for f in FIELDS if f not in have]
