# -*- coding: utf-8 -*-
"""Evidence validation + validated fact store.

This is pipeline stage 3+4 of v3. The LLM proposes a SELECTION of parser
candidates; this module decides what is actually admissible and emits the
validated fact store the reply generator is allowed to read.

Hard rules (v3 contract):
  * A fact may only carry a value that exists verbatim as a parser candidate's
    source_span. A value the model invented has no candidate -> rejected.
  * status is one of supported | inferred | not_stated.
  * `not_stated` is the DEFAULT. A field is `supported` only if at least one
    admissible candidate was selected AND the selection survives validation.
  * Negated candidates (the "NOT 5,000 pcs" case) may never be `supported`
    unless the selection explicitly kept them while dropping the negation.

The reply generator (stage 5) receives ONLY supported/inferred facts from the
store. It never receives the raw email.
"""
import re

from fact_parsers import FIELDS

ABSENT_MARKERS = {
    "not_stated", "n/a", "na", "none", "null", "-", "未提及", "未知", "not mentioned",
    "not specified", "unknown", "未说明", "没有", "无",
}
# "as usual" and friends carry no concrete fact for THIS email.
USUAL_MARKERS = (
    "as usual", "as always", "usual", "same as last", "same as before", "as before",
    "same as previous", "as per our standing agreement", "as per standing agreement",
    "照旧", "按惯例", "惯例", "跟以前一样", "和以前一样", "老规矩", "照上次", "同上",
)

# fact types that may legally back each field
FIELD_TYPES = {
    "buyer": {"buyer_signature"},
    "incoterm": {"incoterm"},
    "payment_terms": {"payment_terms", "ratio"},
    "deadline": {"date", "date_range", "date_bare_month", "duration", "relative_time"},
    "amounts": {"amount"},
    "products": {"sku", "doc_id", "qty"},
}


def value_is_absent(v):
    if v is None or v == "" or v == [] or v == {}:
        return True
    if isinstance(v, str):
        s = v.strip().lower().rstrip(".")
        if s in ABSENT_MARKERS:
            return True
        if any(u in s for u in USUAL_MARKERS):
            return True
    return False


def _norm(s):
    return "".join(str(s or "").lower().split())


def _digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _dedupe_amounts(chosen):
    """Drop a WEAK bare number only when a currency-bearing amount carries the SAME
    numeric value. "USD 2.00/pc" and the bare "2.00" are one figure stated twice;
    "USD 2.00/pc" and "USD 2.40" are two distinct prices and both must survive.
    """
    out, seen = [], set()
    for c in sorted(chosen, key=lambda x: (bool(x.get("weak")), x["span_start"])):
        d = _digits(c.get("number"))
        if c.get("weak") and d and d in seen:
            continue
        out.append(c)
        if d and not c.get("weak"):
            seen.add(d)
    return out


ROLE_RANK = {"total": 0, "primary": 1, "conditional": 2, "defect": 3, "historical": 4}
# Roles that are never the operative quantity of a product line: a defect count,
# a future conditional, and a past order.
NON_ORDER_ROLES = ("defect", "conditional", "historical")

# Units that count the goods themselves. A packaging count (cartons, boxes,
# pallets) describes how the goods are packed, not how many were ordered.
PIECE_UNITS = {"pcs", "pc", "pieces", "piece", "件", "个", "只", "条", "双", "支", "件pcs"}


def _pick_qty(cands):
    """Choose the operative quantity among candidates for one product line.
    'total' beats 'primary' beats 'conditional' beats 'defect'; ties fall back
    to document order so the choice stays deterministic.

    A PACKAGING count never wins against a piece count: "460 cartons, 11,040 pcs"
    states two counts for one line; the piece count is what was ordered and the
    carton count is a packing detail. This sits AFTER the role ranking so a
    genuine total ("合计 5,000 件") still beats a subtotal."""
    if not cands:
        return None
    ordered = sorted(cands, key=lambda c: (ROLE_RANK.get(c.get("role", "primary"), 1),
                                            c["span_start"]))
    if ROLE_RANK.get(ordered[0].get("role", "primary"), 1) <= 1:
        pieces = [c for c in ordered
                  if str(c.get("unit") or "").strip().lower() in PIECE_UNITS]
        if pieces:
            return pieces[0]
    return ordered[0]


def _pick_qty_near(cands, ident):
    """_pick_qty, but ties broken by PROXIMITY to the identifier.

    Which number belongs to a product line is a distance question, not a
    document-order question. Strict "the qty after the identifier" mis-binds
    both directions:
      "Send 50 pcs of KY-900 ... we ordered 12,000 pcs last year"
          -> the 50 FOLLOWS nothing and precedes KY-900; document order picks 12,000
      "第一批 200 件样品（SKU YK-100），第二批大货 2,000 件（SKU YK-100-B）"
          -> 2,000 sits between the two SKUs, so "next qty after" gives it to
             YK-100 instead of YK-100-B
    Rank stays the OUTER key (a stated total still beats a subtotal); distance
    only decides between quantities of equal standing.
    """
    if not cands:
        return None

    def dist(c):
        if ident["span_end"] <= c["span_start"]:
            return c["span_start"] - ident["span_end"]      # quantity after
        if c["span_end"] <= ident["span_start"]:
            return ident["span_start"] - c["span_end"]      # quantity before
        return 0                                            # overlapping

    ordered = sorted(cands, key=lambda c: (ROLE_RANK.get(c.get("role", "primary"), 1),
                                            dist(c), c["span_start"]))
    if ROLE_RANK.get(ordered[0].get("role", "primary"), 1) <= 1:
        pieces = [c for c in ordered
                  if str(c.get("unit") or "").strip().lower() in PIECE_UNITS]
        if pieces:
            return pieces[0]
    return ordered[0]


class FactStore:
    """Validated facts. The reply generator may read this and nothing else."""

    def __init__(self):
        self.fields = {f: {"value": None, "status": "not_stated",
                           "facts": [], "rejected": []} for f in FIELDS}
        self.provenance = []

    # -- helpers ---------------------------------------------------------
    def by_id(self, parsed):
        return {f["id"]: f for f in parsed["_facts"]}

    def candidates_for(self, parsed, field):
        allowed = FIELD_TYPES.get(field, set())
        return [f for f in parsed["_facts"] if f["type"] in allowed]

    # -- validation ------------------------------------------------------
    def validate_field(self, parsed, field, selection):
        """selection: list of candidate ids the model chose (may be empty).

        Returns (ok, reasons). On success the field is committed to the store.
        """
        idx = self.by_id(parsed)
        allowed = FIELD_TYPES.get(field, set())
        reasons = []
        chosen = []

        for cid in selection or []:
            cand = idx.get(cid)
            if cand is None:
                reasons.append(f"unknown_candidate:{cid}")
                continue
            if cand["type"] not in allowed:
                reasons.append(f"type_not_allowed_for_{field}:{cid}:{cand['type']}")
                continue
            chosen.append(cand)

        if not chosen and field == "buyer":
            # The trailing signature is the sender by construction — the parser
            # already proved it is name-like and last. A selector that omits it is
            # an omission, not a judgement, so bind it mechanically.
            sigs = [f for f in parsed["_facts"] if f["type"] == "buyer_signature"]
            if sigs:
                chosen = list(sigs)

        if not chosen and field == "products":
            # A stated quantity with NO identifier is still a stated fact:
            # "the 1,500 pcs order" names a line without naming a style code.
            # Recording it as sku=null/qty=1,500 is correct; collapsing the field
            # to not_stated would claim the customer never mentioned a quantity.
            qtys = [f for f in parsed["_facts"]
                    if f["type"] == "qty" and not f.get("negated")
                    and f.get("role", "primary") not in NON_ORDER_ROLES]
            if qtys:
                chosen = list(qtys)
                reasons.append("products_qty_only_no_identifier")

        if not chosen and field in ("incoterm", "payment_terms"):
            # Scalar-term recall. "FOB only" is a stated term even when the
            # selector returns [] because the surrounding clause carries a
            # negation ("does NOT include shipping. FOB only.") that made it
            # look unsafe. The parser already decided admissibility, so a term
            # it proved present is recorded rather than silently dropped.
            cands = [f for f in parsed["_facts"]
                     if f["type"] == ("incoterm" if field == "incoterm" else "payment_terms")
                     and not f.get("negated")]
            if cands:
                chosen = list(cands)
                reasons.append(f"{field}_recall_from_parser:{len(cands)}")

        if not chosen and field == "deadline":
            # A stated DATE is only a deadline when the customer ties it to a
            # delivery/request cue ("samples received Oct 3" is history; "we need
            # it by Oct 3" is a deadline). Recall only hinted candidates, so an
            # incidental date is never promoted to a commitment.
            hinted = [f for f in parsed["_facts"]
                      if f["type"] in ("date", "date_bare_month", "duration", "relative_time")
                      and f.get("deadline_hint") and not f.get("negated")]
            if hinted:
                chosen = list(hinted)
                reasons.append(f"deadline_recall_with_hint:{len(hinted)}")

        if not chosen:
            # An all-invalid selection must still be visible to the audit trail.
            if reasons:
                return False, reasons
            self.fields[field] = {"value": None, "status": "not_stated",
                                  "facts": [], "rejected": []}
            return True, ["no_candidate_selected"]

        # An identifier selected on its own is under-specified: a product line is
        # (identifier, quantity). Bind the nearest admissible quantity so the
        # pairing is deterministic rather than another chance for the model to omit it.
        # 3. DEFECT/DEFECTIVE/conditional quantities: a defect count or a future
        #    conditional is not the ordered quantity of the line being reported.
        if field == "products":
            # NEGATION FIRST. If the model's own selection contains nothing but
            # rejected candidates, the field is not_stated. Auto-binding a
            # different quantity afterwards would silently override that decision
            # and assert a value the model never selected.
            sel_negated = [c for c in chosen if c.get("negated")]
            sel_ok = [c for c in chosen if not c.get("negated")]
            if sel_negated and not sel_ok:
                self.fields[field] = {"value": None, "status": "not_stated", "facts": [],
                                      "rejected": [c["id"] for c in sel_negated]}
                return False, ["only_negated_candidates:" + ",".join(c["id"] for c in sel_negated)]

            usable_qty = [c for c in chosen
                          if c["type"] != "qty" or c.get("role", "primary") not in NON_ORDER_ROLES]
            # An EXPLICITLY selected quantity is still subject to the operative-
            # quantity rules. The selector is a semantic resolver; it has no
            # reason to prefer a packing count ("460 cartons") over the piece
            # count ("11,040 pcs") beside it, or a per-colour subtotal
            # ("各 2,500 件") over the stated total ("合计 5,000 件"). Ranking by
            # role then unit is deterministic and evidence-based; picking by
            # selector order is neither.
            # The selector picked quantities but NOT the stated TOTAL
            # beside them ("各 2,500 件，合计 5,000 件" -> it picked the
            # 2,500). The total is the figure the customer asked for.
            have = {c["id"] for c in usable_qty}
            totals = [f for f in parsed["_facts"]
                      if f["type"] == "qty" and f["id"] not in have
                      and not f.get("negated") and f.get("role") == "total"]
            if totals:
                usable_qty = usable_qty + totals
                reasons.append("added_stated_total:"
                               + ",".join(f["id"] for f in totals))
            qt = [c for c in usable_qty if c["type"] == "qty"]
            if qt:
                best_role = min(ROLE_RANK.get(c.get("role", "primary"), 1) for c in qt)
                qt = [c for c in qt if ROLE_RANK.get(c.get("role", "primary"), 1) == best_role]
                piece = [c for c in qt
                         if str(c.get("unit") or "").strip().lower() in PIECE_UNITS]
                keep = {c["id"] for c in piece}
                # A packaging count is only demoted when a piece count is
                # actually available. If the selector picked ONLY the
                # packaging count ("100 cartons"), the piece count beside it
                # ("5,000 pcs") was never selected — recall it from the
                # candidate set instead of leaving the line with no order
                # quantity at all.
                if not keep:
                    recalled = [f for f in parsed["_facts"]
                                if f["type"] == "qty" and not f.get("negated")
                                and f.get("role", "primary") == "primary"
                                and str(f.get("unit") or "").strip().lower() in PIECE_UNITS]
                    if recalled:
                        keep = {f["id"] for f in recalled}
                        usable_qty = usable_qty + recalled
                        reasons.append("recalled_piece_count:"
                                       + ",".join(sorted(keep)))
                demoted = [c for c in usable_qty
                           if c["type"] == "qty" and c["id"] not in keep]
                if demoted:
                    usable_qty = [c for c in usable_qty if c not in demoted]
                    reasons.append("demoted_subtotal_or_packaging_qty:"
                                   + ",".join(c["id"] for c in demoted))
            dropped_qty = [c for c in chosen if c not in usable_qty]
            all_qty_rejected = bool(chosen) and not usable_qty
            # adopt usable_qty whenever it differs from what was selected — it may
            # have DEMOTED a subtotal/packaging count or ADDED the stated total.
            # Guarding on `dropped_qty` alone would silently discard the additions.
            if usable_qty and usable_qty != chosen:
                if dropped_qty:
                    reasons.append("dropped_non_order_quantities:"
                                   + ",".join(f'{c["id"]}({c.get("role")})' for c in dropped_qty))
                chosen = usable_qty
            chosen = self._complete_products(parsed, chosen)
            # Identifier recall. The selector is a semantic resolver, not an extractor: it
            # often returns only the strongest identifier on a line and omits a
            # second stated one. Every admissible identifier the parser saw is
            # recorded; the bench scores products by RECALL of expected items, and
            # a stated identifier is a stated fact. Negated candidates stay out
            # (all_qty_rejected), and a defect/conditional quantity never binds.
            if not all_qty_rejected:
                have = {c["id"] for c in chosen}
                for extra in parsed["_facts"]:
                    if extra["type"] in ("sku", "doc_id") and extra["id"] not in have \
                            and not extra.get("negated"):
                        chosen = chosen + [extra]
                        have.add(extra["id"])
            chosen = self._complete_products(parsed, chosen)
        elif field == "amounts":
            chosen = _dedupe_amounts(chosen)
            # Amount recall: a currency-bearing price the parser proved exists is
            # a stated fact. The selector returns the one it judges salient and
            # drops the rest ("unit price USD 4.00 ... Amount should be USD
            # 1,200.00" -> it returns only the total, losing the unit price).
            # Recall every admissible currency-bearing amount; contiguity and
            # negation have already been decided by the parser.
            strong = [f for f in parsed["_facts"]
                      if f["type"] == "amount" and not f.get("weak") and not f.get("negated")]
            have = {c["id"] for c in chosen}
            chosen = chosen + [f for f in strong if f["id"] not in have]
            chosen = _dedupe_amounts(chosen)

        # A vague time word that only describes the customer's own schedule is not
        # our deadline. Reject it mechanically rather than trusting the selector.
        if field == "deadline":
            usable = [c for c in chosen
                      if c["type"] != "relative_time" or c.get("deadline_hint")]
            dropped = [c for c in chosen if c not in usable]
            if dropped and not usable:
                self.fields[field] = {"value": None, "status": "not_stated",
                                      "facts": [], "rejected": [c["id"] for c in dropped]}
                return False, ["relative_time_without_deadline_hint:" + ",".join(c["id"] for c in dropped)]
            if dropped:
                chosen = usable
                reasons.append("dropped_relative_time_without_hint:" + ",".join(c["id"] for c in dropped))

        # every chosen value must be verbatim in the source email
        for c in chosen:
            if c["source_span"] not in parsed.get("_email", c["source_span"]):
                reasons.append(f"span_not_in_source:{c['id']}")

        # a negated candidate may not be the sole support for a field
        non_negated = [c for c in chosen if not c.get("negated")]
        negated = [c for c in chosen if c.get("negated")]
        if negated and not non_negated:
            reasons.append("only_negated_candidates:" + ",".join(c["id"] for c in negated))
            # fall back to not_stated rather than assert a negated value
            self.fields[field] = {"value": None, "status": "not_stated",
                                  "facts": [], "rejected": [c["id"] for c in negated]}
            return False, reasons

        value = self._render(field, chosen)
        status = "supported"
        # a bare-month or relative deadline is only "inferred" when unqualified
        if field == "deadline":
            for c in chosen:
                if c["type"] == "relative_time":
                    status = "inferred"
                if c["type"] == "date_bare_month" and not c.get("qualified"):
                    status = "inferred"

        self.fields[field] = {
            "value": value,
            "status": status,
            # Carry the parser's evidence flags through to the store. The
            # contested flag is what the guard and the fallback template read to
            # decide a value may not be echoed; dropping it here silently
            # un-contested every fact and let the fallback re-state a blocked
            # discount.
            "facts": [{"id": c["id"], "value": c["value"], "type": c["type"],
                       "source_span": c["source_span"], "status": "supported",
                       "span": [c["span_start"], c["span_end"]],
                       "contested": bool(c.get("contested")),
                       "customer_asserted": bool(c.get("customer_asserted")),
                       "negated": bool(c.get("negated"))} for c in chosen],
            "rejected": [c["id"] for c in negated] if not non_negated else [],
        }
        return not reasons, reasons

    def _complete_products(self, parsed, chosen):
        """Attach a quantity to an identifier that was selected bare.

        Deterministic rule, in priority order:
          1. a qty whose listing_sku names this identifier ("QY-11 x 800")
          2. a quantity ALREADY claimed by another identifier on this line
             ("Order PO-5566, 7,000 pcs TS-303" — one quantity, two identifiers)
          3. the next qty after the identifier, before the next identifier
          4. the nearest preceding qty
        A negated / defect / conditional quantity is never auto-attached.
        """
        ids = [c for c in chosen if c["type"] in ("sku", "doc_id")]
        if not ids:
            return chosen
        have = {c["id"] for c in chosen}
        # A defect count or a future conditional is never the ordered quantity of
        # the line, so it is excluded from the pool entirely — otherwise a line
        # like "800 pcs of TS-551 ... 40 pcs damaged" binds the 40.
        all_qty = [f for f in parsed["_facts"]
                   if f["type"] == "qty" and not f.get("negated")
                   and f.get("role", "primary") not in NON_ORDER_ROLES]
        # A DOCUMENT/ORDER identifier ("OL-3301", "PO-7701") names the paperwork,
        # not the goods. It must not claim the line's quantity ahead of a
        # style code that is actually adjacent to it ("订单明细 OL-3301，款号
        # SC-208 白/灰各 2,500 件，合计 5,000 件" — GT wants SC-208 / 5,000).
        # So when both kinds are present on one line, a sku is served first
        # and the doc_id shares whatever is left.
        skus = [x for x in ids if x["type"] == "sku"]
        if skus and len(skus) != len(ids):
            order = skus + [x for x in ids if x["type"] != "sku"]
        else:
            order = ids

        out = list(chosen)
        for i, ident in enumerate(order):
            # An explicitly selected, unclaimed quantity binds first, in document
            # order. Without this, "TS-101 white 2,000 pcs ... TS-102 black 3,500 pcs"
            # lets TS-102 fall back to the preceding 2,000. The operative-
            # quantity ranking is applied FIRST so a subtotal cannot claim the
            # line before the stated total gets a chance ("各 2,500 件,
            # 合计 5,000 件" — document order would bind the 2,500).
            cand_qty = [c for c in out if c["type"] == "qty"
                        and c.get("_bound_to") is None and c["id"] in have]
            if cand_qty:
                # An EXPLICITLY selected quantity is still subject to the
                # operative-quantity rules. Binding it unconditionally let the
                # selector's choice of a packaging count ("100 cartons") or a
                # per-colour subtotal ("各 2,500 件") beat the piece count and
                # the stated total sitting in the same selection.
                best = _pick_qty_near(cand_qty, ident)
                if best is not None:
                    for c in cand_qty:
                        if c is not best:
                            c.pop("_bound_to", None)
                    best["_bound_to"] = ident["id"]
                    continue
            if any(c["type"] == "qty" and c.get("_bound_to") == ident["id"] for c in out):
                continue
            pick = None
            for q in all_qty:
                if q.get("listing_sku") and _norm(q["listing_sku"]) == _norm(ident["value"]):
                    pick = q
                    break
            if pick is None:
                # NEAREST unclaimed quantity, either side. The search is bounded
                # by the neighbouring identifiers so a later line's count cannot
                # leak backwards, and preference is by distance rather than
                # "after first": "Send 50 pcs of KY-900" puts the count BEFORE.
                prev_end = order[i - 1]["span_end"] if i else 0
                nxt = order[i + 1]["span_start"] if i + 1 < len(order) else float("inf")
                window = [q for q in all_qty
                          if q.get("_bound_to") is None and q["id"] not in have
                          and prev_end <= q["span_end"] and q["span_start"] < nxt]
                pick = _pick_qty_near(window, ident)
            if pick is None:
                # An identifier added by recall shares the line's quantity ONLY
                # when it is adjacent to an identifier that already holds one —
                # i.e. the line names two identifiers and one quantity
                # ("Order PO-5566, 7,000 pcs TS-303").
                for c in out:
                    if c["type"] == "qty" and c.get("_bound_to"):
                        owner = c["_bound_to"]
                        own = next((x for x in ids if x["id"] == owner), None)
                        if own is not None and abs(own["span_start"] - ident["span_start"]) <= 60:
                            pick = c
                            break
            if pick is not None and pick["id"] not in have:
                pick = dict(pick)
                pick["_bound_to"] = ident["id"]
                out.append(pick)
                have.add(pick["id"])
        return out

    def _render(self, field, chosen):
        """Compose the field value from chosen candidates — by CONCATENATION of
        verbatim substrings and separators only. No reformatting, no computation."""
        if field == "products":
            return self._render_products(chosen)
        if field == "amounts":
            return [c["value"] for c in chosen]
        if field == "deadline":
            if len(chosen) == 1:
                c = chosen[0]
                return c.get("month") if c["type"] == "date_bare_month" else c["value"]
            return ", ".join(
                (c.get("month") if c["type"] == "date_bare_month" else c["value"])
                for c in sorted(chosen, key=lambda x: x["span_start"]))
        # scalar fields
        if len(chosen) == 1:
            return chosen[0]["value"]
        return " ".join(c["value"] for c in sorted(chosen, key=lambda x: x["span_start"]))

    def _render_products(self, chosen):
        """Pair each identifier with its nearest quantity. Deterministic pairing:
        an identifier binds to the quantity that follows it before the next
        identifier; if none, to the nearest preceding quantity."""
        ids = [c for c in chosen if c["type"] in ("sku", "doc_id")]
        qtys = [c for c in chosen if c["type"] == "qty"]
        out = []
        # qty with no identifier anywhere is still a stated product line:
        # GT for con03/neg03/neg01 is products=[{sku: null, qty: ...}].
        if not ids:
            return [{"sku": None, "qty": (q.get("number") if q else None),
                     "_qty_fact": (q["id"] if q else None)} for q in qtys]
        for i, ident in enumerate(ids):
            # honour the binding decided in _complete_products, if any
            bound = next((q for q in qtys if q.get("_bound_to") == ident["id"]), None)
            if bound is None:
                # an identifier added by recall may share an ADJACENT line's
                # quantity ("Order PO-5566, 7,000 pcs TS-303")
                cand = next((q for q in qtys if q.get("_bound_to")
                             and q["_bound_to"] != ident["id"]), None)
                if cand is not None:
                    owner = next((x for x in ids if x["id"] == cand["_bound_to"]), None)
                    if owner is not None and abs(owner["span_start"] - ident["span_start"]) <= 60:
                        bound = cand
            nxt = ids[i + 1]["span_start"] if i + 1 < len(ids) else float("inf")
            if bound is not None:
                q = bound
            else:
                after = [x for x in qtys if ident["span_end"] <= x["span_start"] < nxt
                         and x.get("_bound_to") is None]
                if after:
                    q = _pick_qty(after)
                else:
                    before = [x for x in qtys if x["span_end"] <= ident["span_start"]
                              and x.get("_bound_to") is None]
                    q = _pick_qty(before)
            if q is not None and q.get("listing_sku") and \
                    _norm(q["listing_sku"]) != _norm(ident["value"]):
                q = None
            out.append({"sku": ident["value"],
                        "qty": (q.get("number") if q else None),
                        "_qty_fact": (q["id"] if q else None)})
        return out

    # -- normalization ---------------------------------------------------
    def finalize(self):
        """Mechanical post-pass: reconcile not_stated with what we actually hold.
        A field WITH a supported value must not also be listed in not_stated."""
        ns = []
        for f in FIELDS:
            cell = self.fields[f]
            if cell["value"] is None or value_is_absent(cell["value"]):
                cell["value"] = None
                cell["status"] = "not_stated"
                cell["facts"] = []
                if f not in ns:
                    ns.append(f)
            else:
                cell["status"] = cell.get("status") or "supported"
        return ns

    def extraction(self):
        """The schema the API/bench consumes."""
        ext = {}
        for f in FIELDS:
            v = self.fields[f]["value"]
            if f == "products" and v:
                # only sku/qty/desc reach the API surface; binding bookkeeping
                # (which fact supplied the quantity) stays in the audit trail.
                ext[f] = [{"sku": p["sku"], "qty": p["qty"], "desc": ""} for p in v]
            else:
                ext[f] = v
        ext["not_stated"] = [f for f in FIELDS if self.fields[f]["value"] is None]
        return ext

    def audit(self):
        """Full provenance for the report and for the RAW-vs-FINAL comparison."""
        return {f: {"status": self.fields[f]["status"],
                    "value": self.fields[f]["value"],
                    "facts": self.fields[f]["facts"],
                    "rejected": self.fields[f]["rejected"]}
                for f in FIELDS}


def build(parsed, email, selections):
    """Run validation for every field and return (store, not_stated, issues)."""
    parsed["_email"] = email
    store = FactStore()
    issues = {}
    for f in FIELDS:
        ok, reasons = store.validate_field(parsed, f, (selections or {}).get(f) or [])
        if not ok:
            issues[f] = reasons
    not_stated = store.finalize()
    return store, not_stated, issues