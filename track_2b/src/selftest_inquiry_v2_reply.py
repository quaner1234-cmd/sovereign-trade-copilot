"""Frozen P5 text-level tests. Live naturalness is reviewed independently."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from inquiry_v2 import analyze
from inquiry_v2.reply_generation import build_contract, generate, normalize_proposal, validate_proposal
from inquiry_v2.source_registry import build
from selftest_inquiry_v2 import FIXTURE as BASE_FIXTURE, payload
from selftest_inquiry_v2_context import source_context

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data/inquiry_v2_reply_acceptance.json"
FIXTURE_SHA256 = "3663e97674ff6fc05152fd821a56916e2c708833009c35e551cb44d723101cde"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in FIXTURE["regressions"]}
BASES = {c["id"]: c for c in BASE_FIXTURE["cases"]}

def combine(*contexts):
    return {"sources": [copy.deepcopy(s) for c in contexts for s in c["sources"]],
            "candidates": [copy.deepcopy(v) for c in contexts for v in c["candidates"]]}

def context_for(kind):
    if kind == "public_and_working_moq":
        refs = [source_context("reference", ident="public-moq-" + str(n), value=n) for n in (100, 300, 500)]
        working = source_context("working", ident="working-moq-300", value=300)
        working["candidates"][0]["provenance"]["derived_from"] = [c["candidates"][0]["id"] for c in refs]
        return combine(*refs, working)
    if kind == "conflicting_moq":
        return combine(source_context("company", ident="policy-a", value=240), source_context("company", ident="policy-b", value=360))
    if kind == "external_shipping_range":
        quote = "China to Germany sea transit reference is 25–35 days"
        s = {"id": "synthetic-carrier", "kind": "public_source", "party": "public", "status": "read", "text": quote,
             "scope": "external.route.sea", "metadata": {"url": "https://carrier.example.invalid/china-germany",
             "publisher": "Synthetic carrier", "access_date": "2026-10-04"}}
        c = {"id": "external-sea-transit", "key": "shipping.transit", "role": "external", "value": {"min": 25, "max": 35},
             "unit": "days", "status": "public_reference", "source_id": s["id"], "scope": s["scope"], "scope_spec": {"global": True},
             "conditions": ["China to Germany", "sea"], "qualifier": "range", "provenance": {"span": [0, len(quote)], "quote": quote, "derived_from": []}}
        return {"sources": [s], "candidates": [c]}
    raise ValueError("unknown synthetic context")

def prepared(ident, context=None):
    case = CASES.get(ident, BASES.get(ident))
    request = payload(case, cold=case.get("cold", False))
    if case.get("context_kind"):
        request["company_context"] = context_for(case["context_kind"])
    if context is not None:
        request["company_context"] = copy.deepcopy(context)
    result, registry = analyze(request), build(request)
    return result, registry, build_contract(result, registry)

def envelope(text, contract, move=None, claims=None, answers=None, questions=None):
    return {"draft": text, "claims": copy.deepcopy(claims or []), "answers": copy.deepcopy(answers or []),
            "questions": copy.deepcopy(questions or []), "next_move": {"text": move or text, "action": contract["judgment"]["action"]}}

def claim(text, fact, role=None, line_ids=None):
    return {"text": text, "candidate_ids": [fact["id"]], "evidence_ids": [],
            "line_ids": fact["line_ids"] if line_ids is None else line_ids, "role": role or fact["role"]}

def company_moq(contract):
    clause = "The standard bulk minimum is 240 pieces per style; colour and material minimums require internal checking."
    move = "The next step is an internal review of the small-lot option."
    qtext = "Could the standard production quantity work for a priority style?"
    fact = next(f for f in contract["permitted_facts"] if f["key"] == "moq.style")
    return envelope(CASES["P5-R10"]["useful_text"], contract, move=move, claims=[claim(clause, fact)],
        answers=[{"text": clause, "obligation_id": a["id"]} for a in contract["answer_obligations"]],
        questions=[{"text": qtext, "question_id": contract["permitted_questions"][0]["id"]}])

def chat_sequence(*proposals):
    from inquiry_v2.reply_semantics import CHECKS, PROMPT
    calls = []
    audit_calls = []
    def chat(messages, **kwargs):
        if messages[0]["content"] == PROMPT:
            audit_calls.append({"messages": copy.deepcopy(messages), "kwargs": copy.deepcopy(kwargs)})
            data = json.loads(messages[-1]["content"])
            # Protocol plumbing only. This fake verdict is not evidence of
            # natural-language quality; deterministic safety gates still run.
            audit = {"checks": {key: True for key in CHECKS}, "issues": [],
                     "speech_acts": [{"text": data["draft"], "kind": "internal_action"}]}
            return json.dumps(audit, ensure_ascii=False), {"mode": "test_semantic_stub", "latency_ms": 1}
        calls.append({"messages": copy.deepcopy(messages), "kwargs": copy.deepcopy(kwargs)})
        value = proposals[min(len(calls) - 1, len(proposals) - 1)]
        return (None if value is None else json.dumps(value, ensure_ascii=False)), {"mode": "test_stub", "latency_ms": 1}
    chat.audit_calls = audit_calls
    # Preserve existing generation-attempt assertions; audit calls are separate
    # observable calls and do not consume a generation proposal sequence.
    return chat, calls

def surface(proposal):
    """Explicit migration of test fixtures to the new application binding wire."""
    slots=[{"item_ids":[a["obligation_id"]],"text":a["text"]} for a in proposal.get("answers",[])]
    move=proposal.get("next_move",proposal.get("move"))
    slots.append({"item_ids":["primary"],"text":move["text"] if isinstance(move,dict) else move})
    slots += [{"item_ids":[q["question_id"]],"text":q["text"]} for q in proposal.get("questions",[])]
    return {"slots":slots,"courtesy":proposal.get("courtesy","")}

class FirstReplyAcceptanceTests(unittest.TestCase):
    def rejected(self, proposal, contract):
        guard = validate_proposal(proposal, contract)
        self.assertFalse(guard["passed"], guard)
        self.assertTrue(guard["issues"])

    def test_frozen_rubric(self):
        self.assertEqual(hashlib.sha256(FIXTURE_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), FIXTURE_SHA256)
        self.assertEqual([c["id"] for c in FIXTURE["representatives"]], ["S0" + str(n) for n in range(1, 8)])

    def test_seven_contracts_preserve_judgment(self):
        for case in FIXTURE["representatives"]:
            with self.subTest(case=case["id"]):
                result, _, contract = prepared(case["id"])
                self.assertEqual(contract["judgment"], result["advance"])
                self.assertEqual(contract["language"], result["reply"]["language"])
                self.assertLessEqual(len(contract["permitted_questions"]), case["max_questions"])
                self.assertTrue(contract["needs_human_approval"])
                self.assertTrue(all(q["changes_decision"] and q["no_re_ask_basis"] for q in contract["permitted_questions"]))

    def test_known_moq_obligation(self):
        for ident in ("S01", "S06", "P5-R10"):
            _, _, contract = prepared(ident)
            self.assertTrue(any(a["key"] == "moq.style" and a["value"] == 240 for a in contract["answer_obligations"]))

    def test_known_moq_answer_admitted(self):
        _, _, contract = prepared("P5-R10")
        guard = validate_proposal(company_moq(contract), contract)
        self.assertTrue(guard["passed"], guard)

    def test_safe_generic_answer_omission_rejected(self):
        _, _, contract = prepared("P5-R10")
        self.rejected(envelope(CASES["P5-R10"]["unsafe_text"], contract), contract)

    def test_cold_start_supports_costing(self):
        result, _, contract = prepared("P5-R01")
        self.assertEqual(result["advance"]["action"], "INTERNAL_COSTING")
        self.assertFalse(any(f["role"] == "company" for f in contract["permitted_facts"]))
        self.assertFalse(contract["permitted_questions"])
        guard = validate_proposal(envelope(CASES["P5-R01"]["useful_text"], contract), contract)
        self.assertTrue(guard["passed"], guard)

    def test_public_and_working_operator_only(self):
        _, _, contract = prepared("P5-R02")
        values = {f["value"] for f in contract["operator_only"] if isinstance(f["value"], int)}
        self.assertTrue({100, 300, 500} <= values)
        self.assertFalse(any(f["key"].startswith("moq") for f in contract["permitted_facts"]))
        self.rejected(envelope(CASES["P5-R02"]["unsafe_text"], contract), contract)

    def test_concrete_external_range_admitted(self):
        _, _, contract = prepared("P5-R03")
        fact = next(f for f in contract["permitted_facts"] if f["role"] == "external")
        self.assertEqual(fact["value"], {"min": 25, "max": 35})
        clause = "For the stated sea route, the carrier reference is 25–35 days in transit."
        move = "Our next step is a preliminary material and construction cost review."
        guard = validate_proposal(envelope(clause + " " + move, contract, move=move, claims=[claim(clause, fact)],
            answers=[{"text": clause, "obligation_id": a["id"]} for a in contract["answer_obligations"]]), contract)
        self.assertTrue(guard["passed"], guard)

    def test_external_cannot_be_company_delivery(self):
        _, _, contract = prepared("P5-R03")
        self.rejected(envelope(CASES["P5-R03"]["unsafe_text"], contract), contract)

    def test_read_thread_attachment_no_reask(self):
        for ident in ("P5-R04", "P5-R06"):
            _, _, contract = prepared(ident)
            self.assertFalse(contract["permitted_questions"])
            self.rejected(envelope(CASES[ident]["unsafe_text"], contract), contract)

    def test_unread_attachment_honesty(self):
        _, _, contract = prepared("P5-R05")
        self.assertTrue(contract["coverage"]["gaps"])
        self.assertFalse(contract["permitted_questions"])
        guard = validate_proposal(envelope(CASES["P5-R05"]["useful_text"], contract), contract)
        self.assertTrue(guard["passed"], guard)
        self.rejected(envelope(CASES["P5-R05"]["unsafe_text"], contract), contract)

    def test_multiple_line_quantity_binding(self):
        _, _, contract = prepared("P5-R07")
        facts = [f for f in contract["permitted_facts"] if f["key"] == "quantity"]
        self.assertEqual({f["value"] for f in facts}, {420, 650})
        lines = {l["id"]: l["product_ref"] for l in contract["lines"]}
        self.assertTrue(any("vest" in lines[f["line_ids"][0]] and f["value"] == 420 for f in facts))
        self.assertTrue(any("bag" in lines[f["line_ids"][0]] and f["value"] == 650 for f in facts))
        self.rejected(envelope(CASES["P5-R07"]["unsafe_text"], contract), contract)

    def test_metadata_cannot_license_swapped_actual_quantity(self):
        _, _, contract = prepared("P5-R07")
        vest = next(f for f in contract["permitted_facts"] if f["key"] == "quantity" and f["value"] == 420)
        bag = next(f for f in contract["permitted_facts"] if f["key"] == "quantity" and f["value"] == 650)
        a, b = "650 work vests", "420 cotton tote bags"
        text = "We will review preliminary costing for " + a + " and " + b + "."
        self.rejected(envelope(text, contract, claims=[claim(a, vest), claim(b, bag)]), contract)

    def test_technical_numbers_are_not_counts(self):
        case = {"body": "Please assess one prototype work vest using 3-layer fabric and 5% stretch. Our waterproof target is 20K."}
        result = analyze(payload(case, cold=True))
        counts = [v["value"] for v in result["values"] if v["key"] == "quantity" and v["status"] != "rejected"]
        self.assertEqual(counts, [1])

    def test_requested_payment_no_company_authority(self):
        _, _, contract = prepared("P5-R08")
        self.assertFalse(any(f["role"] == "company" and "payment" in f["key"] for f in contract["permitted_facts"]))
        self.rejected(envelope(CASES["P5-R08"]["unsafe_text"], contract), contract)

    def test_wrong_text_language_cannot_hide_in_metadata(self):
        _, _, contract = prepared("P5-R09")
        self.assertEqual(contract["language"], "es")
        bad = envelope(CASES["P5-R09"]["unsafe_text"], contract)
        bad["language"] = "es"
        self.rejected(bad, contract)

    def test_internal_labels_fake_attachments_rejected(self):
        _, _, contract = prepared("P5-R11")
        self.rejected(envelope(CASES["P5-R11"]["unsafe_text"], contract), contract)

    def test_unresolved_facts_no_reply_authority(self):
        _, _, contract = prepared("P5-R12")
        self.assertEqual(contract["judgment"]["action"], "INTERNAL_VERIFICATION")
        self.assertFalse(any(f["key"] == "moq.style" for f in contract["permitted_facts"]))
        self.rejected(envelope(CASES["P5-R12"]["unsafe_text"], contract), contract)

    def test_project_exception_no_global_reply_authority(self):
        _, _, contract = prepared("P5-R01", context=source_context("company", scope="project", value=90))
        self.assertFalse(any(f["key"] == "moq.style" for f in contract["permitted_facts"]))
        self.rejected(envelope("Our MOQ is 90 pieces per style. We will review the costing basis.", contract), contract)

    def test_hidden_unsupported_tail_rejected(self):
        _, _, contract = prepared("P5-R01")
        safe = "Our next step is a preliminary material and construction cost review."
        self.rejected(envelope(safe + " We have all certificates and stock available.", contract, move=safe), contract)

    def test_customer_annotation_no_company_stock_authority(self):
        _, _, contract = prepared("P5-R01")
        fact = next(f for f in contract["permitted_facts"] if f["key"] == "product")
        clause = "We have work vests in stock and all performance certifications."
        move = "Our next step is a preliminary cost review."
        self.rejected(envelope(clause + " " + move, contract, move=move, claims=[claim(clause, fact, role="customer")]), contract)

    def test_next_move_no_compound_dispatch(self):
        _, _, contract = prepared("P5-R01")
        self.rejected(envelope("We will review the costing basis and dispatch the work vests tomorrow.", contract), contract)

    def test_one_question_id_no_known_quantity_freight_reask(self):
        _, _, contract = prepared("P5-R10")
        bad = company_moq(contract)
        old = bad["questions"][0]["text"]
        question = "Could the standard quantity work, and what quantity and collection address do you need?"
        bad["draft"] = bad["draft"].replace(old, question)
        bad["questions"][0]["text"] = question
        self.rejected(bad, contract)

    def test_moq_same_number_wrong_unit_rejected(self):
        _, _, contract = prepared("P5-R10")
        bad = company_moq(contract)
        for record in bad["claims"] + bad["answers"]:
            record["text"] = record["text"].replace("pieces per style", "sets per style")
        bad["draft"] = bad["draft"].replace("pieces per style", "sets per style")
        self.rejected(bad, contract)

    def test_four_questions_rejected(self):
        _, _, contract = prepared("S07")
        qs = contract["permitted_questions"]
        texts = [q["question"] for q in qs] * 2
        move = "Our next step is a preliminary review."
        bad = envelope(" ".join(texts) + " " + move, contract, move=move,
            questions=[{"text": text, "question_id": qs[i % len(qs)]["id"]} for i, text in enumerate(texts)])
        self.rejected(bad, contract)

    def test_answer_metadata_requires_actual_value(self):
        _, _, contract = prepared("P5-R10")
        text = "Thank you. The next step is an internal review of the small-lot option."
        bad = envelope(text, contract, answers=[{"text": text, "obligation_id": a["id"]} for a in contract["answer_obligations"]])
        self.rejected(bad, contract)

    def test_retry_retains_known_answer_and_same_contract(self):
        result, registry, contract = prepared("P5-R10")
        good=surface(company_moq(contract)); bad=copy.deepcopy(good)
        bad["slots"][0]["text"] += " We guarantee a factory price of USD 1.25."
        repair={"repairs":[{"slot_index":0,"text":good["slots"][0]["text"]}]}
        chat,calls=chat_sequence(bad,repair)
        reply=generate(result,registry,chat_fn=chat)
        self.assertEqual(reply["status"],"ready_for_review",reply)
        self.assertEqual(reply["path"],"slot_retry")
        self.assertIn("240",reply["draft"])
        self.assertEqual(reply["attempts"][0]["plan_hash"],reply["attempts"][1]["plan_hash"])
        self.assertTrue(reply["attempts"][1]["unchanged_slots_byte_identical"])
        self.assertTrue(reply["needs_human_approval"])

    def test_retry_safe_empty_withheld_without_template(self):
        result,registry,contract=prepared("P5-R10")
        bad=surface(company_moq(contract)); bad["slots"][0]["text"] += " We guarantee USD 1.25."
        chat,calls=chat_sequence(bad,{"repairs":[{"slot_index":0,"text":"Thank you."}]})
        reply=generate(result,registry,chat_fn=chat)
        self.assertEqual(reply["status"],"withheld")
        self.assertIsNone(reply["draft"])
        self.assertEqual(len(calls),2)
        self.assertFalse(reply["guard"]["passed"])
        self.assertFalse(reply["attempts"][1]["required_content_preserved"])

    def test_model_unavailable_no_fake_composed_reply(self):
        result, registry, _ = prepared("P5-R01")
        chat, calls = chat_sequence(None)
        reply = generate(result, registry, chat_fn=chat)
        self.assertEqual(reply["status"], "unavailable")
        self.assertIsNone(reply["draft"])
        self.assertEqual(len(calls), 1)

    def test_generation_preserves_input(self):
        result, registry, contract = prepared("P5-R01")
        before = copy.deepcopy((result, registry, contract))
        chat, _ = chat_sequence(envelope(CASES["P5-R01"]["useful_text"], contract))
        generate(result, registry, chat_fn=chat)
        self.assertEqual((result, registry, contract), before)

    def test_external_asked_range_cannot_be_omitted(self):
        _, _, contract = prepared("P5-R03")
        self.assertTrue(any(a["key"] == "shipping.transit" for a in contract["answer_obligations"]))
        self.rejected(envelope("Our next step is a preliminary material and construction cost review.", contract), contract)

    def test_chinese_fullwidth_question_uses_known_moq_answer(self):
        context = source_context("company", value=240)
        source = context["sources"][0]
        source["text"] = "标准起订量是240件每款。"
        candidate = context["candidates"][0]
        candidate["provenance"].update(quote=source["text"], span=[0, len(source["text"])])
        case = {"body": "需要18件马甲，标准起订量是多少？我们自己的货代提货。"}
        request = payload(case, cold=True)
        request["company_context"] = context
        result, registry = analyze(request), build(request)
        contract = build_contract(result, registry)
        self.assertEqual(contract["language"], "zh")
        self.assertTrue(contract["answer_obligations"])
        fact = next(f for f in contract["permitted_facts"] if f["key"] == "moq.style")
        clause, move = "标准起订量是240件每款。", "接下来先评估小批量方案。"
        proposal = envelope(clause + move, contract, move=move, claims=[claim(clause, fact)],
            answers=[{"text": clause, "obligation_id": a["id"]} for a in contract["answer_obligations"]])
        guard = validate_proposal(proposal, contract)
        self.assertTrue(guard["passed"], guard)
        wire=surface(proposal)
        wire["slots"] += [{"item_ids":[q["id"]],"text":"标准起订数量是否可以接受？"} for q in contract["permitted_questions"]]
        chat, _ = chat_sequence(wire)
        reply = generate(result, registry, chat_fn=chat)
        self.assertEqual(reply["status"], "ready_for_review", reply)
        self.assertIn("240", reply["draft"])
        wrong = copy.deepcopy(proposal)
        wrong["draft"] = "The MOQ is 240 pieces per style. We will review the small lot."
        self.rejected(wrong, contract)

    def test_polish_and_thai_wrong_text_language_rejected(self):
        for body, expected in (("Dzień dobry, proszę o wstępną cenę na 420 work vests. Ilość jest podana.", "pl"),
                               ("สวัสดีค่ะ ต้องการสอบถามราคา 420 work vests จำนวนตามนี้ค่ะ", "th")):
            with self.subTest(language=expected):
                request = payload({"body": body}, cold=True)
                result, registry = analyze(request), build(request)
                contract = build_contract(result, registry)
                self.assertEqual(contract["language"], expected)
                self.rejected(envelope("Our next step is a preliminary material and construction cost review.", contract), contract)

    def test_confirmed_price_payment_and_leadtime_answers(self):
        examples = [
            ("bulk_price", 27.40, "USD", "Our approved factory price is USD 27.40.", "What factory price applies to 420 work vests?"),
            ("payment_terms", "T/T", None, "Our payment terms are T/T.", "What payment terms apply to 420 work vests?"),
            ("lead_time.normal", 95, "days", "Our normal lead time is 95 days.", "What is the normal lead time for 420 work vests?")]
        for key, value, unit, clause, body in examples:
            with self.subTest(term=key):
                context = source_context("company", value=240)
                source, candidate = context["sources"][0], context["candidates"][0]
                source["text"] = clause
                candidate.update(key=key, value=value, unit=unit)
                candidate["provenance"].update(quote=clause, span=[0, len(clause)])
                request = payload({"body": body}, cold=True)
                request["company_context"] = context
                result, registry = analyze(request), build(request)
                contract = build_contract(result, registry)
                self.assertTrue(contract["answer_obligations"])
                fact = next(f for f in contract["permitted_facts"] if f["key"] == key)
                move = "Our next step is a preliminary material and construction cost review."
                proposal = envelope(clause + " " + move, contract, move=move, claims=[claim(clause, fact)],
                    answers=[{"text": clause, "obligation_id": a["id"]} for a in contract["answer_obligations"]])
                guard = validate_proposal(proposal, contract)
                self.assertTrue(guard["passed"], guard)
                self.rejected(envelope(move, contract), contract)

    def test_customer_quantity_cannot_supply_company_price(self):
        _, _, contract = prepared("P5-R01")
        self.rejected(envelope("Our price is USD 420. Our next step is a review.", contract), contract)

    def test_chinese_work_vest_scope_matches_qualified_product(self):
        context = source_context("company", value=240, scope="category")
        request = payload({"body": "需要18件工装马甲，标准起订量是多少？"}, cold=True)
        request["company_context"] = context
        result, registry = analyze(request), build(request)
        contract = build_contract(result, registry)
        self.assertTrue(any(f["key"] == "moq.style" and f["value"] == 240 for f in contract["permitted_facts"]))
        self.assertTrue(contract["answer_obligations"])

    def test_chinese_generic_vest_cannot_inherit_work_vest_policy(self):
        context = source_context("company", value=240, scope="category")
        request = payload({"body": "需要18件马甲，标准起订量是多少？"}, cold=True)
        request["company_context"] = context
        result, registry = analyze(request), build(request)
        contract = build_contract(result, registry)
        self.assertFalse(any(f["key"] == "moq.style" for f in contract["permitted_facts"]))

    def test_language_slots_bind_authority_and_join_text_once(self):
        result, registry, contract = prepared("P5-R10")
        good = company_moq(contract)
        slots = {"answers": good["answers"], "move": {"text": good["next_move"]["text"]},
                 "questions": good["questions"], "facts": [], "courtesy": "Thank you."}
        # The model supplies only language/IDs; the application supplies source,
        # role, line scope and action from the existing immutable contract.
        proposal = normalize_proposal(slots, contract)
        self.assertEqual(proposal["claims"][0]["role"], "company")
        self.assertEqual(proposal["next_move"]["action"], contract["judgment"]["action"])
        self.assertEqual(proposal["draft"].count("240"), 1)
        self.assertEqual(proposal["draft"].count(good["next_move"]["text"]), 1)
        guard = validate_proposal(proposal, contract)
        self.assertTrue(guard["passed"], guard)
        chat, _ = chat_sequence(surface(slots))
        reply = generate(result, registry, chat_fn=chat)
        self.assertEqual(reply["status"], "ready_for_review", reply)
        self.assertEqual(reply["draft"], proposal["draft"])

    def test_language_slots_cannot_manufacture_fact_authority(self):
        _, _, contract = prepared("P5-R01")
        unknown = {"answers": [], "move": {"text": "Our next step is a preliminary cost review."},
                   "questions": [], "facts": [{"candidate_id": "invented-company-price", "text": "Our price is USD 27.40."}]}
        with self.assertRaises(ValueError):
            normalize_proposal(unknown, contract)

    def test_language_slot_customer_fact_cannot_be_company_promise(self):
        _, _, contract = prepared("P5-R01")
        fact = next(f for f in contract["permitted_facts"] if f["key"] == "product")
        slots = {"answers": [], "move": {"text": "Our next step is a preliminary material and construction cost review."},
                 "questions": [], "facts": [{"candidate_id": fact["id"], "text": "We have work vests in stock."}]}
        proposal = normalize_proposal(slots, contract)
        self.assertEqual(proposal["claims"][0]["role"], "customer")
        self.rejected(proposal, contract)

    def test_language_slot_answer_must_actually_state_condition(self):
        _, _, contract = prepared("P5-R10")
        slots = {"answers": [{"obligation_id": a["id"], "text": "Thank you for your inquiry."} for a in contract["answer_obligations"]],
                 "move": {"text": "Our next step is an internal review of the small-lot option."}, "questions": [], "facts": []}
        self.rejected(normalize_proposal(slots, contract), contract)

    def test_language_slot_courtesy_cannot_hide_unapproved_terms(self):
        _, _, contract = prepared("P5-R01")
        slots = {"answers": [], "move": {"text": "Our next step is a preliminary material and construction cost review."},
                 "questions": [], "facts": [], "courtesy": "Hello. Our MOQ is 300 pieces per style."}
        self.rejected(normalize_proposal(slots, contract), contract)

    def test_courtesy_cannot_smuggle_certified_company_products(self):
        _, _, contract = prepared("P5-R01")
        move = "Our next step is a preliminary material and construction cost review."
        self.rejected(envelope("Thank you for choosing our certified products. " + move, contract, move=move), contract)

    def test_confirmed_price_currency_and_identifier_boundaries(self):
        context = source_context("company", value=240)
        source, candidate = context["sources"][0], context["candidates"][0]
        source["text"] = "Our approved factory price is USD 27.40."
        candidate.update(key="bulk_price", value=27.40, unit="USD")
        candidate["provenance"].update(quote=source["text"], span=[0, len(source["text"])])
        request = payload({"body": "What factory price applies to 420 work vests?"}, cold=True)
        request["company_context"] = context
        result, registry = analyze(request), build(request)
        contract = build_contract(result, registry)
        fact = next(f for f in contract["permitted_facts"] if f["key"] == "bulk_price")
        move = "Our next step is a preliminary material and construction cost review."
        for unsupported in ("EUR 27.40.", "USD 27.40X.", "USD TS-2740.", "USD 27,40."):
            with self.subTest(value=unsupported):
                clause = "Our approved factory price is " + unsupported
                proposal = envelope(clause + " " + move, contract, move=move, claims=[claim(clause, fact)],
                    answers=[{"text": clause, "obligation_id": a["id"]} for a in contract["answer_obligations"]])
                self.rejected(proposal, contract)

    def test_scalar_move_repairs_shape_without_new_business_permissions(self):
        result, registry, contract = prepared("P5-R01")
        move = "Our next step is a preliminary material and construction cost review."
        slots = {"answers": [], "move": move, "questions": [], "facts": [], "courtesy": "Thank you."}
        normalized = normalize_proposal(slots, contract)
        self.assertEqual(normalized["next_move"]["text"], move)
        self.assertEqual(normalized["next_move"]["action"], contract["judgment"]["action"])
        chat, _ = chat_sequence(surface(slots))
        reply = generate(result, registry, chat_fn=chat)
        self.assertEqual(reply["status"], "ready_for_review", reply)

    def test_schema_error_retry_is_precise_and_contract_stays_fixed(self):
        result,registry,_=prepared("P5-R01")
        bad={"slots":[{"item_ids":["invented-policy"],"text":"Our MOQ is 300."}]}
        chat,calls=chat_sequence(bad)
        reply=generate(result,registry,chat_fn=chat)
        self.assertEqual(reply["status"],"withheld")
        self.assertIn("invalid_slot_binding",reply["guard"]["issues"])
        self.assertEqual(len(calls),1,"Invalid plan bindings cannot trigger renderer replanning")

    def test_external_carrier_reference_cannot_be_our_catalogue(self):
        _, _, contract = prepared("P5-R03")
        fact = next(f for f in contract["permitted_facts"] if f["role"] == "external")
        move = "Our next step is a preliminary material and construction cost review."
        clause = "Our catalogue gives a China to Germany sea transit reference of 25–35 days."
        bad = envelope(clause + " " + move, contract, move=move, claims=[claim(clause, fact)],
                       answers=[{"text": clause, "obligation_id": a["id"]} for a in contract["answer_obligations"]])
        self.rejected(bad, contract)

    def test_external_reference_does_not_transfer_to_air_or_different_destination(self):
        _, _, contract = prepared("P5-R03")
        fact = next(f for f in contract["permitted_facts"] if f["role"] == "external")
        move = "Our next step is a preliminary material and construction cost review."
        for clause in ("The carrier reference is 25–35 days for air transit from China to Germany.",
                       "The carrier reference is 25–35 days for sea transit from China to Canada."):
            with self.subTest(route=clause):
                bad = envelope(clause + " " + move, contract, move=move, claims=[claim(clause, fact)],
                               answers=[{"text": clause, "obligation_id": a["id"]} for a in contract["answer_obligations"]])
                self.rejected(bad, contract)

    def test_english_inquiry_rejects_entire_chinese_or_thai_reply(self):
        _, _, contract = prepared("P5-R01")
        self.assertEqual(contract["language"], "en")
        for text in ("接下来先评估面料和结构成本，再提出初步报价。",
                     "ขั้นตอนต่อไปเราจะตรวจสอบวัสดุและต้นทุนการตัดเย็บก่อนเสนอราคา"):
            with self.subTest(text=text):
                self.rejected(envelope(text, contract), contract)

if __name__ == "__main__":
    unittest.main(verbosity=2)
