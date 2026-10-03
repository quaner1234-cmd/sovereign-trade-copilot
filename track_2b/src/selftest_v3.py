# -*- coding: utf-8 -*-
"""v3 offline self-test. No model calls.

Two properties are checked:
  A. parser reachability — every GT value is visible to the deterministic layer.
  B. guard safety — with a DELIBERATELY BAD reply, the final guard must block it
     and the deterministic fallback must not contain any unvouched number.

Property B is the one that matters for the thesis: the pipeline must be unable
to ship a fabricated number even if the model produces one.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fact_parsers as FP
import fact_store as FS
import pipeline_v3 as P3
import semantics as SEM

CASES = json.load(open(os.path.join(HERE, "..", "data", "bench", "cases.json"), encoding="utf-8"))["cases"]
FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------- A. ceiling
def test_ceiling():
    print("\nA. parser reachability (offline)")
    import audit_parser_ceiling as APC
    miss = APC.main()
    check("every GT value reachable", not miss.get("ALL") and not any(miss.values()),
          f"unreachable: { {k: v for k, v in miss.items() if v} }")


# ------------------------------------------------------------- B. guard safety
BAD_DRAFTS = [
    "您好，已确认价格 USD 9,999/pc，共 123,456 件，交期 2027-03-15。",   # all invented
    "We will deliver all 888,000 pcs by Dec 30 guaranteed.",            # promise + invented
    "已同意 20% 定金，发货前付 80%。",                                 # restates assertion
    "",                                                                # empty
]


def test_guard():
    print("\nB. final guard blocks bad drafts (offline)")
    email = "Please quote 3,000 pcs TS-660 CIF Hamburg. Sarah Lau"
    parsed = FP.collect(email)
    parsed["_email"] = email
    store, not_stated, _ = FS.build(parsed, email, {
        "buyer": [], "products": [f["id"] for f in parsed["_facts"] if f["type"] == "sku"],
        "incoterm": [f["id"] for f in parsed["_facts"] if f["type"] == "incoterm"],
        "payment_terms": [], "deadline": [], "amounts": []})

    for i, bad in enumerate(BAD_DRAFTS):
        ok, clean, issues = P3.guard_reply(bad, store, email)
        check(f"guard blocks bad draft #{i+1}", not ok, f"issues={issues}")

    fb = P3._fallback_reply(store, not_stated)
    ok_fb, _, fb_issues = P3.guard_reply(fb, store, email)
    check("fallback itself passes guard", ok_fb, f"issues={fb_issues} text={fb!r}")
    # "invents no numbers" is the number/promise guard's claim, so it is measured
    # with that guard. The FULL semantic guard is a different claim, asserted
    # immediately below: this flat legacy template predates the semantic layer and
    # must be refused whenever the customer left a value unsettled ("please quote
    # ... CIF"), because it records their request as a settled fact. That is why
    # checked_fallback() tries the role-aware template first and why this template
    # is only reachable for all-FACT emails.
    ok_legacy_full, _, legacy_full = P3.guard_reply(fb, store, email, FP.collect(email),
                                                    SEM.build_typed(email, FP.collect(email), store))
    check("fallback invents no numbers", not P3.guard_reply(fb, store, email)[2],
          f"leaked {P3.guard_reply(fb, store, email)[2]}")
    check("legacy template refused when a customer value is unsettled",
          not ok_legacy_full, f"unexpectedly accepted: {fb!r}")
    role_aware = P3._fallback_reply(store, not_stated,
                                    SEM.build_typed(email, FP.collect(email), store), email)
    ok_ra, _, ra_issues = P3.guard_reply(role_aware, store, email, FP.collect(email),
                                         SEM.build_typed(email, FP.collect(email), store))
    check("role-aware fallback is what ships instead", ok_ra, f"issues={ra_issues} text={role_aware!r}")

    # a good draft must pass
    good = "您好，TS-660 3,000 件 CIF Hamburg 的需求已记录，贸易术语与付款条款我司将尽快核实后回复。"
    ok_good, _, gi = P3.guard_reply(good, store, email)
    check("guard passes a compliant draft", ok_good, f"issues={gi}")


# --------------------------------------------------------- C. store integrity
def test_store():
    print("\nC. evidence layer integrity (offline)")

    # invented candidate id is rejected, not trusted
    email = "Please quote 3,000 pcs TS-660. Sarah Lau"
    parsed = FP.collect(email); parsed["_email"] = email
    store, ns, issues = FS.build(parsed, email, {
        "buyer": ["f999"], "products": [f["id"] for f in parsed["_facts"] if f["type"] == "sku"],
        "incoterm": [], "payment_terms": [], "deadline": [], "amounts": []})
    check("unknown candidate id rejected", "f999" not in json.dumps(store.audit(), ensure_ascii=False),
          json.dumps(store.fields["buyer"], ensure_ascii=False))
    check("unknown id reported", any("unknown_candidate" in r for r in issues.get("buyer", [])),
          str(issues))

    # negated-only selection must become not_stated, never supported
    em2 = "Correction: the quantity is 5,500 pcs, NOT 5,000 pcs. SKU stays TS-001. Maria Lopez"
    p2 = FP.collect(em2); p2["_email"] = em2
    neg = [f["id"] for f in p2["_facts"] if f.get("negated") and f["type"] == "qty"]
    good = [f["id"] for f in p2["_facts"] if f["type"] == "qty" and not f.get("negated")]
    st2, ns2, _ = FS.build(p2, em2, {"products": neg, "buyer": [], "incoterm": [],
                                     "payment_terms": [], "deadline": [], "amounts": []})
    check("negated-only selection -> not_stated",
          st2.fields["products"]["value"] is None, json.dumps(st2.fields["products"], ensure_ascii=False))
    # the affirmative qty alone is under-specified; the store binds the SKU to it
    st3, ns3, _ = FS.build(p2, em2, {"products": good, "buyer": [], "incoterm": [],
                                     "payment_terms": [], "deadline": [], "amounts": []})
    vals = st3.fields["products"]["value"] or []
    check("affirmative qty binds with the SKU",
          any(v["qty"] == "5,500" for v in vals), json.dumps(vals, ensure_ascii=False))
    st3b, _, _ = FS.build(p2, em2, {"products": good + ["f003"], "buyer": [], "incoterm": [],
                                     "payment_terms": [], "deadline": [], "amounts": []})
    v3 = st3b.fields["products"]["value"] or []
    check("affirmative qty + sku -> correct pair",
          any(v["sku"] == "TS-001" and v["qty"] == "5,500" for v in v3),
          json.dumps(v3, ensure_ascii=False))

    # "as usual" must be not_stated even if the model claims otherwise
    em4 = "Please arrange the next shipment for PO-6612 as usual to Hamburg. 2,400 pcs. Payment as usual too. Markus Weber"
    p4 = FP.collect(em4); p4["_email"] = em4
    st4, ns4, _ = FS.build(p4, em4, {"buyer": [], "products": [], "incoterm": [],
                                      "payment_terms": ["f_usual"], "deadline": [], "amounts": []})
    check("absent-ish value -> not_stated",
          "payment_terms" in ns4, f"not_stated={ns4}")

    # double-reporting fix: a supported field must not also be in not_stated
    em5 = "Quote CIF Hamburg for 2,000 pcs TS-101 at USD 2.10 by Dec 1. Gary O'Neill"
    p5 = FP.collect(em5); p5["_email"] = em5
    sel5 = {f: [x["id"] for x in p5["_facts"] if x["type"] in FS.FIELD_TYPES[f]] for f in FS.FIELDS}
    sel5["products"] = [x["id"] for x in p5["_facts"] if x["type"] in ("sku", "doc_id")]
    st5, ns5, _ = FS.build(p5, em5, sel5)
    ext5 = st5.extraction()
    check("no field both valued and not_stated",
          all(not (ext5[f] is not None and f in ext5["not_stated"]) for f in FS.FIELDS),
          json.dumps(ext5, ensure_ascii=False))


# ------------------------------------------------------------- D. prompt sanity
def test_prompts():
    print("\nD. prompt contract (offline)")
    P = P3.PROMPTS
    check("intent enum has 5 members", len(P["INTENT_ENUM"]) == 5, str(P["INTENT_ENUM"]))
    check("selector forbids writing values",
          "must NOT write values" in P["select"]["system"], "")
    check("reply prompt forbids unvouched values",
          "Use only values present in the FACTS list" in P["reply"]["system"], "")
    check("reply prompt never receives the raw email",
          "{email}" not in P["reply"]["user"], P["reply"]["user"][:120])
    check("deadline types include relative_time",
          "relative_time" in P["select"]["system"], "")


def test_g5_invariants():
    """Invariants behind individually-diagnosed G5 failures.

    Each of these was a real failure found by replaying recorded selections.
    They are cheap to assert offline, and every one of them silently reverts if
    the parser is retuned for another case.
    """
    print("\n-- G5 invariants (regression-locked) --")

    def parsed(email):
        p = FP.collect(email)
        p["_email"] = email
        return p

    # A negation that governs a VERB does not negate a later quantity.
    # "No rush on the 3,300 pcs TS-444" — the 3,300 is what was ordered.
    f = [x for x in parsed("No rush on the 3,300 pcs TS-444 - anytime in December is fine.")["_facts"]
         if x["type"] == "qty" and str(x.get("number")) == "3,300"]
    check("verb negation does not negate a later quantity", bool(f) and not f[0].get("negated"))

    # "Do not send the PI yet for the 1,500 pcs order" negates SENDING.
    f = [x for x in parsed("Do not send the PI yet for the 1,500 pcs order. "
                           "Wait for our confirmation.")["_facts"]
         if x["type"] == "qty" and str(x.get("number")) == "1,500"]
    check("'do not send' does not negate the order quantity",
          bool(f) and not f[0].get("negated"))

    # A negation binds ONLY the immediately following value: in
    # "quantity was 300 pcs not 3,000 pcs, unit price USD 4.00" the "not"
    # governs the 3,000; the 4.00 is introduced by a fresh noun phrase.
    p = parsed("Please reissue invoice INV-4471-B: quantity was 300 pcs not 3,000 pcs, "
               "unit price USD 4.00. Amount should be USD 1,200.00.")
    amts = {str(x.get("value")): x.get("negated") for x in p["_facts"] if x["type"] == "amount"}
    check("negation does not cross a comma into the next clause",
          amts.get("USD 4.00") is False and amts.get("USD 1,200.00") is False)
    qt = {str(x.get("value")): x.get("negated") for x in p["_facts"] if x["type"] == "qty"}
    check("'not 3,000 pcs' still negates the 3,000", qt.get("3,000 pcs") is True
          and qt.get("300 pcs") is False)

    # A quantity with no identifier is still a stated fact, not not_stated.
    em = "Do not send the PI yet for the 1,500 pcs order. Wait for our confirmation."
    st, ns, _ = FS.build(parsed(em), em, {})
    prods = st.extraction().get("products") or []
    check("qty-only product is recorded, not dropped to not_stated",
          len(prods) == 1 and prods[0].get("qty") == "1,500")

    # A defect count must never become the line's ordered quantity.
    em = ("the 800 pcs of TS-551 arrived with broken cartons, roughly 40 pcs damaged. "
          "We need replacements.")
    st, _, _ = FS.build(parsed(em), em, {})
    prods = st.extraction().get("products") or []
    check("defect qty does not replace the ordered qty",
          bool(prods) and str(prods[0].get("qty")) == "800")

    # A contested value must be refused by the guard even without confirmation
    # language — echoing the customer's negotiating position IS the failure.
    em = "Our budget is USD 2.00/pc for the 10,000 pcs JK-220 order. Rui Wang"
    p = parsed(em)
    st, _, _ = FS.build(p, em, {})
    ok, _, iss = P3.guard_reply("已记录 SKU JK-220 数量 10,000 件，单价 USD 2.00/件。", st, em, p)
    check("guard refuses to echo a contested value",
          (not ok) and any("contested" in i for i in iss))

    # A CLEAN email whose number is NOT contested must survive the same guard.
    em = "Please quote 10,000 pcs of TS-001 at USD 2.00/pc, FOB Shanghai. Rui Wang"
    p = parsed(em)
    st, _, _ = FS.build(p, em, {})
    ok, _, iss = P3.guard_reply("已确认 SKU TS-001，数量 10,000 件，单价 USD 2.00/件。", st, em, p)
    check("guard still allows a non-contested price (no over-block)", ok)

    # Scalar-term recall: a stated Incoterm must survive a selector that returns
    # [] because the neighbouring clause carries a negation ("does NOT include
    # shipping. FOB only."). The parser proved FOB is present and un-negated.
    em = ("Quote USD 3.15 for JK-512, 2,000 pcs - note this price does NOT include "
          "shipping. FOB only. Delivery would be 45 days after PO, not 30. Victor Hu")
    st, _, _ = FS.build(parsed(em), em, {"incoterm": []})
    check("stated incoterm survives an empty selector",
          st.extraction().get("incoterm") == "FOB")

    # Deadline recall must NOT promote an incidental past-tense date:
    # "samples received Oct 3" is history, not a delivery commitment.
    em = ("Thanks for the 2,400 pcs TS-330 samples received Oct 3. Quality looks good. "
          "Also, can you send your 2027 holiday calendar?")
    st, _, _ = FS.build(parsed(em), em, {"deadline": []})
    check("incidental past-tense date is not promoted to a deadline",
          st.extraction().get("deadline") is None)

    # ...but a date under a request cue IS a deadline and must be recalled.
    em = "We need the 3,000 pcs TS-901 in Hamburg by Oct 3. Please confirm."
    st, _, _ = FS.build(parsed(em), em, {"deadline": []})
    check("requested date is recalled as the deadline",
          st.extraction().get("deadline") == "Oct 3")

    # Amount recall: every currency-bearing price the parser proved is stated,
    # including one the selector judged less salient than the total.
    em = ("Please reissue invoice INV-4471-B: quantity was 300 pcs not 3,000 pcs, "
          "unit price USD 4.00. Amount should be USD 1,200.00. Sara Haddad")
    st, _, _ = FS.build(parsed(em), em, {"amounts": ["f005"]})
    amts = " ".join(st.extraction().get("amounts") or [])
    check("both unit price and total are recorded",
          "4.00" in amts and "1,200.00" in amts)

    # A PACKAGING count is not the ordered quantity: "460 cartons, 11,040 pcs,
    # SKU JK-450" states two counts for one line; 11,040 is what was ordered.
    # The selection mirrors the real one (sku + both quantities), since that is
    # the path the benchmark exercises.
    em = ("Two files attached.\nAnnex A: invoice INV-2026-88 total USD 15,300.00.\n"
          "Annex B: packing list, 460 cartons, 11,040 pcs, SKU JK-450.\n"
          "Please confirm receipt. Petra")
    pq = parsed(em)
    # mirror the benchmark selection exactly: style code first, then the two
    # competing counts, so this exercises the real demote+bind path
    skus = [f["id"] for f in pq["_facts"] if f["type"] == "sku"]
    qtys = [f["id"] for f in pq["_facts"] if f["type"] == "qty"]
    st, _, _ = FS.build(pq, em, {"products": skus + qtys})
    prods = st.extraction().get("products") or []
    k450 = [p for p in prods if p.get("sku") == "JK-450"]
    check("piece count beats carton count for the same line",
          bool(k450) and str(k450[0].get("qty")) == "11,040")

    # Same rule for a slash-separated pair: "100 cartons / 5,000 pcs TS-002".
    em = ("Container CLHU4471447 loaded with 100 cartons / 5,000 pcs TS-002. "
          "Seal number 4471447. Please book the survey. Henri Dubois")
    st, _, _ = FS.build(parsed(em), em, {})
    prods = st.extraction().get("products") or []
    ts = [p for p in prods if p.get("sku") == "TS-002"]
    check("piece count beats carton count after a slash",
          bool(ts) and str(ts[0].get("qty")) == "5,000")

    # A per-colour SUBTOTAL loses to the stated TOTAL, even when the selector
    # picked only the subtotal ("各 2,500 件，合计 5,000 件" -> 5,000).
    em = ("附件1：订单明细 OL-3301，款号 SC-208 白/灰各 2,500 件，合计 5,000 件。\n"
          "附件2：付款条款，T/T 30% 定金，余款见提单副本。\n请回复确认。大连恒远 周敏")
    p2 = parsed(em)
    # the benchmark's real selection picks the style codes and the SUBTOTAL but
    # not the total — that omission is exactly what this rule has to repair
    sel = [f["id"] for f in p2["_facts"] if f["type"] in ("sku", "doc_id")]
    sel += [f["id"] for f in p2["_facts"]
            if f["type"] == "qty" and f.get("role") != "total"]
    st, _, _ = FS.build(p2, em, {"products": sel})
    prods = st.extraction().get("products") or []
    sc = [p for p in prods if p.get("sku") == "SC-208"]
    check("stated total beats a per-colour subtotal",
          bool(sc) and str(sc[0].get("qty")) == "5,000")

    # PROXIMITY, not document order. Which number belongs to a line is a distance
    # question: "Send 50 pcs of KY-900" puts the count BEFORE the identifier, and
    # "第一批 200 件（YK-100），第二批 2,000 件（YK-100-B）" puts 2,000 BETWEEN the
    # two SKUs. Strict "next qty after" mis-binds all three.
    em = ("两批货：第一批 200 件样品（SKU YK-100），第二批大货 2,000 件（SKU YK-100-B）。"
          "YKK 拉链，100% 纯棉。请分别报价。宁波盛丰 吴迪")
    p3 = parsed(em)
    sk = [f["id"] for f in p3["_facts"] if f["type"] in ("sku", "doc_id")]
    st, _, _ = FS.build(p3, em, {"products": sk})
    got = {q["sku"]: str(q.get("qty")) for q in (st.extraction().get("products") or [])}
    check("quantity binds by proximity, not document order",
          got.get("YK-100") == "200" and got.get("YK-100-B") == "2,000")

    # A PAST order is not this order: "we ordered 12,000 pcs last year ... send 50
    # pcs of KY-900" must bind 50, not the historical 12,000. The cue is scoped
    # to the text AFTER the number, so ind01's "like last season" (which modifies
    # a PRICE, not the live 10,000 pcs) is untouched.
    em = ("Since we ordered 12,000 pcs last year (PO-2025-0817), you owe us the free "
          "samples of the new catalogue, correct? Send 50 pcs of KY-900. Vladimir Petrov")
    p4 = parsed(em)
    # mirror the real selection: the SKU AND the historical quantity
    sk = [f["id"] for f in p4["_facts"] if f["type"] in ("sku", "doc_id")]
    sk += [f["id"] for f in p4["_facts"] if f["type"] == "qty"]
    st, _, _ = FS.build(p4, em, {"products": sk})
    got = {q["sku"]: str(q.get("qty")) for q in (st.extraction().get("products") or [])}
    check("a historical quantity never binds to the current line",
          got.get("KY-900") == "50")

    em = ("Is the unit price still USD 2.40 like last season? If yes we take 10,000 pcs "
          "of TS-001 right away. Marco Rossi")
    p5 = parsed(em)
    sk = [f["id"] for f in p5["_facts"] if f["type"] in ("sku", "doc_id")]
    qt = [f["id"] for f in p5["_facts"] if f["type"] == "qty"]
    st, _, _ = FS.build(p5, em, {"products": sk + qt})
    got = {q["sku"]: str(q.get("qty")) for q in (st.extraction().get("products") or [])}
    check("a historical cue about the PRICE leaves the live quantity alone",
          got.get("TS-001") == "10,000")

    # A CJK document label is context, not part of the identifier. \w matches CJK,
    # so the naive pattern produced the value "订单明细 OL-3301".
    em = ("附件1：订单明细 OL-3301，款号 SC-208 白/灰各 2,500 件，合计 5,000 件。\n"
          "请回复确认。大连恒远 周敏")
    p6 = parsed(em)
    ids6 = {f["value"] for f in p6["_facts"] if f["type"] in ("sku", "doc_id")}
    check("a CJK label is not swallowed into the identifier value",
          "OL-3301" in ids6 and not any("订单" in v or "明细" in v for v in ids6))

    # Shipping equipment is not merchandise: a container number matches the SKU
    # shape and must not claim the line's quantity.
    em = ("Container CLHU4471447 loaded with 100 cartons / 5,000 pcs TS-002. "
          "Seal number 4471447. Please book the survey. Henri Dubois")
    p7 = parsed(em)
    ids7 = {f["value"] for f in p7["_facts"] if f["type"] in ("sku", "doc_id")}
    check("a container number is not a product identifier",
          "CLHU4471447" not in ids7 and "TS-002" in ids7)


if __name__ == "__main__":
    test_ceiling()
    test_guard()
    test_store()
    test_prompts()
    test_g5_invariants()
    print("\n" + "=" * 60)
    print("SELFTEST:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.exit(1 if FAILS else 0)