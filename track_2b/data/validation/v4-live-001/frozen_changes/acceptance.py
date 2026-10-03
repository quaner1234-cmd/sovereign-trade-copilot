# -*- coding: utf-8 -*-
"""Business-owner acceptance tests for the v4 semantic layer. Offline, no model calls.

WHY THIS FILE IS SEPARATE FROM cases.json
The 48-case benchmark measures EXTRACTION against a fixed ground truth. These
tests measure something different and incompatible: whether the system knows
WHAT THE CUSTOMER WAS DOING with a value. Mixing them would mean editing the
benchmark whenever the semantic model moves, so the two are kept apart on
purpose and neither modifies the other.

WHAT MAKES THESE TESTS REAL RATHER THAN A PATCH FOR ONE EMAIL
Each case is paired with a POLARITY CONTROL that must NOT trigger it:

  acc02 target price    <-> acc06 "please confirm the price you quoted" (QUESTION)
  acc07 agreed price    <-> acc02 the same numeric shape is theirTARGET, not a deal
  acc08 real order      <-> acc04 "Initial order would be around 2,500 pcs" (no order)
  acc03 requested date  <-> incidental past-tense dates stay FACT/ignored

A rule hard-coded from the ski-jackets email would fail at least one control.

Run:  python src/acceptance.py
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fact_parsers as FP
import fact_store as FS
import pipeline_v3 as P3
import semantics as SEM

CASES = [
    {
        "id": "acc01_new_inquiry",
        "note": "plain inquiry: no price, no date, nothing to negotiate",
        "email": ("Hi Alex,\n\nWe saw your catalogue and would like to hear more about your "
                  "yoga pants.\nCould you send prices for 500 pcs?\n\nThanks,\nEmma Doyle"),
        "expect": {
            "products_contain": ["yoga pants"],
            "quantity": "500",
            "order_act": False,
            "no_role": ["TARGET", "COMMITMENT"],
            "missing_asked": ["payment_terms"],
        },
    },
    {
        "id": "acc02_target_price",
        "note": "TARGET role: a price goal, not a deal",
        "email": ("Hello Alex,\n\nFor the TS-880 softshell jackets we are aiming for USD 18.50/pc. "
                  "Volume would be 3,000 pcs.\nCan you work with that?\n\nRegards,\nLukas Meier"),
        "expect": {
            "typed": [{"value": "USD 18.50", "semantic_role": "TARGET", "status": "unconfirmed"}],
            "quantity": "3,000",
            "order_act": False,
            "draft_must_contain": ["目标"],
            "draft_must_not_contain": ["我方确认", "已确认", "报价为"],
        },
    },
    {
        "id": "acc03_requested_delivery",
        "note": "requested delivery must keep both the role and the relation",
        "email": ("Hi Alex,\n\nThe TS-901 padded jackets must arrive in Hamburg no later than Dec 5. "
                  "Please confirm you can make it.\n\nBest,\nNora Fischer"),
        "expect": {
            "typed": [{"value": "Dec 5", "semantic_role": "REQUEST", "relation": "before"}],
            "order_act": False,
            "draft_must_contain": ["要求交期"],
            "draft_must_not_contain": ["我司确认", "我方确认"],
        },
    },
    {
        "id": "acc04_approx_quantity",
        "note": "approximate quantity keeps its hedge; and this is NOT an order",
        "email": ("Hi Alex,\n\nInitial run would be around 2,500 pcs of your canvas totes, "
                  "roughly 500 units per colour.\nCould you quote?\n\nThanks,\nPriya Raman"),
        "expect": {
            "quantity": "2,500",
            "qualifier_kind": "approx",
            "products_contain": ["canvas totes"],
            "order_act": False,
            "draft_must_contain": ["约"],
            "draft_must_not_contain": ["订单"],
        },
    },
    {
        "id": "acc05_incoterm_port",
        "note": "Incoterm and its named place are two facts, not one",
        "email": ("Hello,\n\nPlease quote CIF Rotterdam for 1,200 pcs TS-445 winter beanies. "
                  "Our target landed price is EUR 3.20.\n\nRegards,\nSofia Almeida"),
        "expect": {
            "incoterm": "CIF",
            "port": "Rotterdam",
            "typed": [{"value": "EUR 3.20", "semantic_role": "TARGET"}],
            "order_act": False,
        },
    },
    {
        "id": "acc06_confirm_existing_quote",
        "note": "POLARITY CONTROL for TARGET: they ask us to confirm OUR quoted price",
        "email": ("Hi Alex,\n\nYou quoted 6,000 pcs RS-204 sleeping bags at USD 7.85 on Nov 3. "
                  "Is that still valid for a December shipment?\n\nPlease confirm.\nKarim Haddad"),
        "expect": {
            "typed": [{"value": "USD 7.85", "semantic_role": "QUESTION"}],
            "no_role": ["TARGET", "COMMITMENT"],
            "order_act": False,
            "draft_must_not_contain": ["我方确认", "我司确认", "已确认", "订单"],
        },
    },
    {
        "id": "acc07_claims_agreed_price",
        "note": "POLARITY CONTROL: 'we agreed' is their claim about a past deal, not our record",
        "email": ("Alex,\n\nWe agreed on USD 2.05 for the 8,000 pcs TS-330 order last month. "
                  "Your invoice shows USD 2.30.\nPlease honour the agreed price and reissue.\n\n"
                  "Tomas Novak"),
        "expect": {
            "typed": [{"value": "USD 2.05", "semantic_role": "COMMITMENT",
                       "stance": "customer_claimed_prior", "status": "unconfirmed"}],
            "order_act": False,
            "no_company_commitment": True,
            "draft_must_not_contain": ["我方确认", "我司确认", "已确认", "同意"],
        },
    },
    {
        "id": "acc08_confirmed_order",
        "note": "INQUIRY vs ORDER: a real PO plus a live commitment IS an order",
        "email": ("Alex,\n\nPO-8821 is confirmed. Please proceed with 4,000 pcs TS-770 down "
                  "jackets at USD 3.10, FOB Ningbo, shipment before Mar 1.\n"
                  "Payment by LC at sight.\n\nBest,\nGrace Tan"),
        "expect": {
            "order_act": True,
            "incoterm": "FOB",
            "port": "Ningbo",
            "quantity": "4,000",
            "no_company_commitment": True,
            "draft_must_contain": ["订单"],
            "draft_must_not_contain": ["询盘", "我方确认"],
        },
    },
    {
        "id": "acc09_manual_ski_jackets",
        "note": "the business-owner case that started this refactor",
        "email": ("Hi Alex,\n\nWe are interested in your ski jackets.\n"
                  "Initial order would be around 300 pcs.\n"
                  "Our target price is USD 45 and we need delivery before Dec 20.\n"
                  "Could you quote FOB Qingdao?\n\nBest regards,\nDavid"),
        "expect": {
            "products_contain": ["ski jackets"],
            "quantity": "300",
            "qualifier_kind": "approx",
            "incoterm": "FOB",
            "port": "Qingdao",
            "typed": [
                {"value": "USD 45", "semantic_role": "TARGET", "status": "unconfirmed"},
                {"value": "Dec 20", "semantic_role": "REQUEST", "relation": "before"},
            ],
            "order_act": False,
            "no_company_commitment": True,
            "draft_must_contain": ["ski jackets", "约 300 pcs", "目标", "要求交期", "Qingdao"],
            "draft_must_not_contain": ["订单", "我方确认", "我司确认", "已确认", "报价 USD 45"],
        },
    },
]

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def run_case(case):
    email = case["email"]
    exp = case["expect"]
    print(f"\n-- {case['id']}: {case['note']}")
    parsed = FP.collect(email)
    store, not_stated, _ = FS.build(parsed, email, P3._demo_selections(parsed))
    typed = SEM.build_typed(email, parsed, store)
    draft = P3._fallback_reply(store, not_stated, typed, email)
    gissues = P3.guard_reply(draft, store, email, parsed, typed)[2]
    print(f"     draft: {draft}")

    return evaluate_case(case, typed, draft, gissues)


def evaluate_case(case, typed, draft, gissues):
    """The same frozen expectations apply to offline and live results."""
    email = case["email"]
    exp = case["expect"]

    check(case["id"] + ": draft passes the guard", not gissues, str(gissues))

    facts_txt = " ".join(json.dumps(t, ensure_ascii=False) for t in typed)

    if "typed" in exp:
        for want in exp["typed"]:
            hit = [t for t in typed
                   if all(t.get(k) == v for k, v in want.items() if k != "value")
                   and want["value"] in t["value"]]
            check(f"{case['id']}: {want['value']} as {want.get('semantic_role')}", bool(hit),
                  f"got {[t['value'] + ':' + t['semantic_role'] + ':' + t['stance'] for t in typed]}")
    if "no_role" in exp:
        for role in exp["no_role"]:
            bad = [t for t in typed if t["semantic_role"] == role]
            check(f"{case['id']}: no {role} role", not bad,
                  str([t["value"] for t in bad]))
    if "quantity" in exp:
        check(f"{case['id']}: quantity {exp['quantity']}",
              any(t["fact_type"].endswith("quantity") and t["value"].startswith(exp["quantity"])
                  for t in typed),
              str([t["value"] for t in typed if "quantity" in t["fact_type"]]))
    if "qualifier_kind" in exp:
        kinds = {t.get("qualifier", {}).get("kind")
                 for t in typed if "quantity" in t["fact_type"]}
        check(f"{case['id']}: qualifier {exp['qualifier_kind']}",
              exp["qualifier_kind"] in kinds, str(kinds))
    if "products_contain" in exp:
        names = [t["value"] for t in typed if t["fact_type"] == "product"]
        for p in exp["products_contain"]:
            check(f"{case['id']}: product '{p}'", p in names, str(names))
    if "incoterm" in exp:
        got = [t for t in typed if "incoterm" in t["fact_type"]]
        check(f"{case['id']}: incoterm {exp['incoterm']}",
              any(t["value"] == exp["incoterm"] for t in got), str(got))
    if "port" in exp:
        ports = [t.get("named_place") for t in typed if t.get("named_place")]
        check(f"{case['id']}: port {exp['port']}", exp["port"] in ports, str(ports))
    if "order_act" in exp:
        got = SEM.order_act(typed, email)
        check(f"{case['id']}: order_act == {exp['order_act']}", got == exp["order_act"], str(got))
    if exp.get("no_company_commitment"):
        check(f"{case['id']}: no company commitment",
              SEM.company_commitments(typed) == [], str(SEM.company_commitments(typed)))
    for tok in exp.get("draft_must_contain", []):
        check(f"{case['id']}: draft contains '{tok}'", tok in draft, draft)
    for tok in exp.get("draft_must_not_contain", []):
        check(f"{case['id']}: draft avoids '{tok}'", tok not in draft, draft)
    return {"id": case["id"], "typed": typed, "draft": draft, "order_act": SEM.order_act(typed, email)}


# ----------------------------------------------------------------- guard tests
def test_guard_blocks():
    print("\n-- guard: role contract is enforced mechanically --")
    email = ("Hi Alex,\n\nOur target price is USD 45 for around 300 pcs of TS-201 fleece jackets. "
             "We need delivery before Dec 20.\n\nDavid")
    parsed = FP.collect(email)
    store, not_stated, _ = FS.build(parsed, email, P3._demo_selections(parsed))
    typed = SEM.build_typed(email, parsed, store)

    bad_cases = [
        ("target written as our quote", "我司报价 USD 45，可接受。"),
        ("target with confirmation", "贵司目标价格 USD 45，我方确认可行。"),
        ("inquiry written as an order", "已收到贵司订单，300 pcs TS-201。"),
        ("requested date as settled delivery", "交期 Dec 20，届时发货。"),
    ]
    for name, draft in bad_cases:
        issues = P3.guard_reply(draft, store, email, parsed, typed)[2]
        check(f"guard blocks: {name}", bool(issues), draft)

    good = "贵司目标价格 USD 45（我司评估后回复）。贵司要求交期 Dec 20 前，我司核实后回复。"
    issues = P3.guard_reply(good, store, email, parsed, typed)[2]
    check("guard allows a correctly framed reply", not issues, str(issues))

    # with a real order act, order language must be allowed (no over-block)
    em2 = ("Alex,\n\nPO-8821 is confirmed. Please proceed with 4,000 pcs TS-770 down jackets "
           "at USD 3.10, FOB Ningbo, shipment before Mar 1.\nBest, Grace Tan")
    p2 = FP.collect(em2)
    s2, ns2, _ = FS.build(p2, em2, P3._demo_selections(p2))
    t2 = SEM.build_typed(em2, p2, s2)
    issues = P3.guard_reply("您好，已收到贵司订单 PO-8821，产品 TS-770 数量 4,000，我司核实后回复。",
                            s2, em2, p2, t2)[2]
    check("order language allowed when an order act exists (no over-block)", not issues, str(issues))


def test_generalisation():
    """The same rules must hold for phrasings that appear in NO acceptance case.

    These are the anti-hardcode checks: each is a sentence shape unseen during
    rule authoring, run through the same classifier.
    """
    print("\n-- generalisation: unseen phrasings --")
    inputs = [
        ("Our budget is EUR 12.40 per piece.", "amount", "TARGET"),
        ("Our target cost is USD 3.00.", "amount", "TARGET"),
        ("目标价为 USD 3.00。", "amount", "TARGET"),
        ("Is the unit price still USD 2.40?", "amount", "QUESTION"),
        ("Can you confirm the price is still EUR 4.10?", "amount", "QUESTION"),
        ("We agreed on USD 2.05 last month.", "amount", "COMMITMENT"),
        ("我们确认订购 5,000 pcs TS-100。", "qty", "COMMITMENT"),
        ("We need 5,000 pcs TS-100 by Nov 1.", "date", "REQUEST"),
        ("Please quote 5,000 pcs TS-100 FOB Shanghai.", "incoterm", "REQUEST"),
        ("Deliver the sleeping bags to Rotterdam by Oct 3.", "date", "REQUEST"),
    ]
    for sent, kind, want in inputs:
        p = FP.collect(sent)
        cands = [f for f in p["_facts"] if f["type"].startswith(kind)]
        if not cands:
            check(f"unseen '{sent[:32]}' parsed", False, "no candidate")
            continue
        role = SEM.classify(sent, cands[0])[0]
        check(f"unseen '{sent[:34]}' -> {want}", role == want, f"got {role}")


def main():
    results = []
    for c in CASES:
        results.append(run_case(c))
    test_guard_blocks()
    test_generalisation()
    print("\n" + "=" * 62)
    print("ACCEPTANCE:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    return results


if __name__ == "__main__":
    main()
    sys.exit(1 if FAILS else 0)
