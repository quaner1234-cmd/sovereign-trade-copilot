"""P5.1 general business regressions; synthetic data, no live model calls.

These tests protect source state, polarity and primary/parallel advances.
Private held-out inputs and real inquiries are deliberately absent.
"""
import copy
import json
import unittest

from inquiry_v2 import analyze
from inquiry_v2.reply_generation import build_contract, generate, normalize_proposal, validate_proposal
from inquiry_v2.reply_semantics import CHECKS, PROMPT, review
from inquiry_v2.source_registry import build
from selftest_inquiry_v2 import payload
from selftest_inquiry_v2_context import source_context


def prepared(body, *, context=None, attachments=None, references=None):
    request = payload({"body": body}, cold=True)
    request["company_context"] = context or {}
    request["inquiry"]["attachments"] = attachments or []
    request["inquiry"]["referenced_urls"] = references or []
    result = analyze(request)
    registry = build(request)
    return result, build_contract(result, registry)


def move_proposal(text, contract):
    return {"draft": text, "claims": [], "answers": [], "questions": [],
            "next_move": {"text": text, "action": contract["judgment"]["action"]}}


def minimum_proposal(move, contract):
    fact = next(f for f in contract["permitted_facts"] if f["key"] == "moq.style")
    answer = "The standard MOQ is 180 pieces per style."
    questions = [{"text": q.get("text") or q["question"], "question_id": q["id"]}
                 for q in contract["permitted_questions"]]
    return {"draft": "\n\n".join([answer, move] + [q["text"] for q in questions]),
            "claims": [{"text": answer, "candidate_ids": [fact["id"]],
                        "evidence_ids": [], "line_ids": fact["line_ids"], "role": "company"}],
            "answers": [{"text": answer, "obligation_id": a["id"]}
                        for a in contract["answer_obligations"]],
            "questions": questions,
            "next_move": {"text": move, "action": contract["judgment"]["action"]}}


def passing_receipt(proposal, contract):
    """Mock wire/binding only; an all-true verdict must not override hard facts."""
    def chat(messages, **kwargs):
        draft = json.loads(messages[-1]["content"])["draft"]
        result = {"checks": {name: True for name in CHECKS}, "issues": [],
                  "speech_acts": [{"text": draft, "kind": "internal_action"}]}
        return json.dumps(result), {"mode": "test_semantic_stub"}
    return review(proposal, contract, chat)


class FirstReplyBusinessRegressionTests(unittest.TestCase):
    def test_primary_alias_has_explicit_independent_parallel_model(self):
        result, contract = prepared("Please assess 420 work vests with a zipped front and two pockets.")
        advance = result["advance"]
        self.assertIsInstance(advance.get("primary_advance"), dict)
        self.assertEqual(advance["action"], advance["primary_advance"]["action"])
        self.assertIsInstance(advance.get("parallel_reversible_advances"), list)
        self.assertEqual(contract["judgment"], advance)

    def test_material_verification_leads_conditional_parallel_cost_review(self):
        result, _ = prepared(
            "Please assess 420 work vests with genuine licensed reflective material. "
            "Please review the material rights and technical route first, and prepare "
            "a rough construction cost basis in parallel only subject to that verification.")
        advance = result["advance"]
        self.assertEqual(advance["action"], "INTERNAL_VERIFICATION")
        parallel = advance.get("parallel_reversible_advances", [])
        costing = [item for item in parallel if item.get("action") == "INTERNAL_COSTING"]
        self.assertTrue(costing, advance)
        for item in costing:
            self.assertTrue(item.get("conditions") or item.get("condition"), item)

    def test_unread_technical_material_precedes_costing_and_reask(self):
        result, contract = prepared(
            "Please cost one prototype work vest with a zipped front. "
            "The drawing and material brief are attached; review them first.",
            attachments=[{"name": "fictional-drawing.pdf", "status": "referenced_unread"}])
        self.assertEqual(result["advance"]["action"], "INTERNAL_VERIFICATION")
        self.assertTrue(contract["coverage"]["gaps"])
        self.assertFalse(contract["permitted_questions"], contract["permitted_questions"])

    def test_below_minimum_does_not_invent_existing_design(self):
        context = source_context("company", ident="generic-minimum", value=180)
        result, _ = prepared("Please assess 36 work vests. What is the standard MOQ?", context=context)
        self.assertEqual(result["advance"]["action"], "ALIGN_MOQ")
        tasks = " ".join(item["task"] for item in result["advance"]["internal_checks"])
        self.assertNotRegex(tasks, r"(?i)(?:existing|supplied|provided)\s+(?:priority\s+)?(?:design|drawing|reference)")

    def test_absent_design_cannot_be_claimed_as_customer_provided(self):
        context = source_context("company", ident="generic-minimum", value=180)
        _, contract = prepared("Please assess 36 work vests. What is the standard MOQ?", context=context)
        proposal = minimum_proposal(
            "I will review the below-minimum option and the existing design reference you provided.", contract)
        self.assertFalse(validate_proposal(proposal, contract)["passed"])

    def test_actual_moq_answer_survives_source_precondition_fix(self):
        context = source_context("company", ident="generic-minimum", value=180)
        _, contract = prepared("Please assess 36 work vests. What is the standard MOQ?", context=context)
        self.assertTrue(any(a["key"] == "moq.style" and a["value"] == 180
                            for a in contract["answer_obligations"]))
        proposal = minimum_proposal("I will review the below-minimum quantity route internally.", contract)
        guard = validate_proposal(proposal, contract)
        self.assertTrue(guard["passed"], guard)

    def test_enumerated_known_conditions_create_answer_obligation(self):
        context = source_context("company", ident="generic-minimum", value=180)
        _, contract = prepared(
            "Please provide the following for 360 work vests: MOQ, material options and production review basis.",
            context=context)
        self.assertTrue(any(a["key"] == "moq.style" and a["value"] == 180
                            for a in contract["answer_obligations"]))

    def test_unasked_policy_does_not_become_mechanical_answer_obligation(self):
        context = source_context("company", ident="generic-minimum", value=180)
        _, contract = prepared("Please review 360 work vests with a zipped front and two pockets.", context=context)
        self.assertFalse(any(a["key"] == "moq.style" for a in contract["answer_obligations"]))

    def test_negative_specification_cue_is_not_positive_customization(self):
        result, _ = prepared("Please assess 420 work vests without logo customization.")
        for line in result["understanding"]["lines"]:
            for cue in line["spec_cues"]:
                if "logo" in cue["text"].lower():
                    stance = cue.get("polarity", cue.get("semantic_stance"))
                    self.assertIn(stance, {"negative", "negated", "unspecified", "unknown", "not_requested", "not_stated"}, cue)

    def test_positive_customization_cue_is_preserved(self):
        result, _ = prepared("Please assess 420 work vests with logo placement on the front.")
        cues = [cue for line in result["understanding"]["lines"] for cue in line["spec_cues"]
                if "logo" in cue["text"].lower()]
        self.assertTrue(cues)
        self.assertTrue(any(cue.get("polarity", cue.get("semantic_stance"))
                            in {"positive", "affirmative", "requested"} for cue in cues), cues)

    def test_public_unspecified_customization_preserves_uncertainty(self):
        listing = {"id": "fictional-public-reference", "url": "https://example.invalid/reference",
                   "status": "read", "text": "A work vest with two pockets; no logo customization is stated.",
                   "access_date": "2026-10-04"}
        result, _ = prepared("Please assess the work vest in the reference.", references=[listing])
        cues = [cue for line in result["understanding"]["lines"] for cue in line["spec_cues"]
                if cue.get("source_id") == listing["id"] and "logo" in cue["text"].lower()]
        self.assertTrue(all(cue.get("polarity", cue.get("semantic_stance"))
                            in {"negative", "negated", "unspecified", "unknown", "not_stated"} for cue in cues), cues)

    def test_known_unchanged_route_is_not_reasked(self):
        result, contract = prepared("I want the referenced work vest unchanged and without logo customization.")
        self.assertFalse(any(q["field"] == "customization" for q in contract["permitted_questions"]))
        self.assertTrue(any(q["field"] == "quantity" for q in result["advance"]["customer_questions"]))

    def test_verifying_dispatch_is_not_dispatch_approval(self):
        _, contract = prepared("Please assess one evaluation sample work vest with no changes.")
        text = "I will review the sample route and confirm whether we can ship after the route is approved."
        guard = validate_proposal(move_proposal(text, contract), contract)
        self.assertTrue(guard["passed"], guard)

    def test_dispatch_promise_is_still_rejected(self):
        _, contract = prepared("Please assess one evaluation sample work vest with no changes.")
        text = "I will review the sample route and we will dispatch the sample now."
        self.assertFalse(validate_proposal(move_proposal(text, contract), contract)["passed"])

    def test_future_unread_attachment_review_is_not_completed_reading(self):
        _, contract = prepared("Please review the attached work vest technical brief.",
            attachments=[{"name": "fictional-brief.pdf", "status": "referenced_unread"}])
        text = "I will open and review the attached technical brief to establish the construction and sample route."
        guard = validate_proposal(move_proposal(text, contract), contract)
        self.assertTrue(guard["passed"], guard)

    def test_completed_reading_without_source_is_rejected(self):
        _, contract = prepared("Please review the attached work vest technical brief.",
            attachments=[{"name": "fictional-brief.pdf", "status": "referenced_unread"}])
        text = "We have reviewed the attached technical brief and will now assess construction costing."
        self.assertFalse(validate_proposal(move_proposal(text, contract), contract)["passed"])

    def test_unread_does_not_become_customer_omission(self):
        _, contract = prepared("Please review the attached work vest technical brief.",
            attachments=[{"name": "fictional-brief.pdf", "status": "referenced_unread"}])
        text = "You have not provided a technical brief; our next step is a sample review."
        self.assertFalse(validate_proposal(move_proposal(text, contract), contract)["passed"])

    def test_ordered_wire_binds_known_answers_without_model_ids(self):
        context = source_context("company", ident="generic-minimum", value=180)
        _, contract = prepared("Please assess 36 work vests. What is the standard MOQ?", context=context)
        language = {"answers": ["The standard MOQ is 180 pieces per style."],
                    "primary_move": "I will review the below-minimum quantity route internally.",
                    "parallel_moves": [],
                    "questions": [q.get("text") or q["question"] for q in contract["permitted_questions"]]}
        proposal = normalize_proposal(language, contract)
        self.assertEqual(proposal["claims"][0]["role"], "company")
        self.assertEqual(proposal["next_move"]["action"], contract["judgment"]["action"])
        self.assertEqual(proposal["draft"].count("180"), 1)
        self.assertTrue(validate_proposal(proposal, contract)["passed"])

    def test_semantic_receipt_is_bound_to_exact_draft(self):
        _, contract = prepared("Please assess 420 work vests with two pockets.")
        proposal = move_proposal("Our next step is a preliminary construction cost review.", contract)
        receipt = passing_receipt(proposal, contract)
        changed = copy.deepcopy(proposal)
        changed["draft"] += " We will dispatch the goods now."
        guard = validate_proposal(changed, contract, semantic_review=receipt)
        self.assertFalse(guard["passed"])
        self.assertIn("semantic_review_failed_or_unbound", guard["issues"])

    def test_semantic_receipt_is_bound_to_exact_contract(self):
        _, contract = prepared("Please assess 420 work vests with two pockets.")
        _, other = prepared("Please assess 421 work vests with two pockets.")
        proposal = move_proposal("Our next step is a preliminary construction cost review.", contract)
        receipt = passing_receipt(proposal, contract)
        self.assertNotEqual(contract["contract_hash"], other["contract_hash"])
        guard = validate_proposal(proposal, other, semantic_review=receipt)
        self.assertFalse(guard["passed"])
        self.assertIn("semantic_review_failed_or_unbound", guard["issues"])

    def test_passing_semantic_verdict_cannot_authorize_unknown_number(self):
        _, contract = prepared("Please assess 420 work vests with two pockets.")
        proposal = move_proposal("I will review construction costing at USD 19.85.", contract)
        guard = validate_proposal(proposal, contract, semantic_review=passing_receipt(proposal, contract))
        self.assertFalse(guard["passed"])
        self.assertTrue(any("unsupported_number" in issue or "unsupported_amount" in issue
                            for issue in guard["issues"]), guard)

    def test_passing_semantic_verdict_cannot_change_authorized_currency(self):
        context = source_context("company", ident="generic-price", value=180)
        source, candidate = context["sources"][0], context["candidates"][0]
        source["text"] = "Our approved factory price is USD 32.60."
        candidate.update(key="bulk_price", value=32.60, unit="USD")
        candidate["provenance"].update(quote=source["text"], span=[0, len(source["text"])])
        _, contract = prepared("What factory price applies to 420 work vests?", context=context)
        fact = next(f for f in contract["permitted_facts"] if f["key"] == "bulk_price")
        clause = "Our approved factory price is EUR 32.60."
        move = "Our next step is a construction cost review."
        proposal = {"draft": clause + " " + move,
                    "claims": [{"text": clause, "candidate_ids": [fact["id"]], "evidence_ids": [],
                                "line_ids": fact["line_ids"], "role": "company"}],
                    "answers": [{"text": clause, "obligation_id": a["id"]} for a in contract["answer_obligations"]],
                    "questions": [], "next_move": {"text": move, "action": contract["judgment"]["action"]}}
        guard = validate_proposal(proposal, contract, semantic_review=passing_receipt(proposal, contract))
        self.assertFalse(guard["passed"])
        self.assertIn("unsupported_amount_or_currency", guard["issues"])

    def test_passing_semantic_verdict_cannot_erase_known_answer(self):
        context = source_context("company", ident="generic-minimum", value=180)
        _, contract = prepared("Please assess 36 work vests. What is the standard MOQ?", context=context)
        proposal = minimum_proposal("I will review the below-minimum quantity route internally.", contract)
        proposal["draft"] = proposal["draft"].replace("The standard MOQ is 180 pieces per style.\n\n", "")
        proposal["answers"], proposal["claims"] = [], []
        guard = validate_proposal(proposal, contract, semantic_review=passing_receipt(proposal, contract))
        self.assertFalse(guard["passed"])
        self.assertTrue(any(issue.startswith("missing_known_answer:") for issue in guard["issues"]), guard)

    def test_semantic_failure_withholds_lexically_valid_reply(self):
        request = payload({"body": "Please assess 420 work vests with two pockets."}, cold=True)
        result, registry = analyze(request), build(request)
        contract = build_contract(result, registry)
        move = "Our next step is a preliminary construction cost review."
        self.assertTrue(validate_proposal(move_proposal(move, contract), contract)["passed"])
        audit_calls = []
        def chat(messages, **kwargs):
            if messages[0]["content"] == PROMPT:
                draft = json.loads(messages[-1]["content"])["draft"]
                audit_calls.append(draft)
                checks = {name: True for name in CHECKS}
                checks["grounded_claims"] = False
                response = {"checks": checks,
                            "issues": [{"check": "grounded_claims", "text": draft,
                                        "reason": "Controlled negative semantic verdict for gate testing."}],
                            "speech_acts": [{"text": draft, "kind": "internal_action"}]}
            else:
                response = {"slots": [{"item_ids": ["primary"], "text": move}]}
            return json.dumps(response), {"mode": "test_semantic_negative"}
        reply = generate(result, registry, chat_fn=chat)
        self.assertEqual(reply["status"], "withheld")
        self.assertIsNone(reply["draft"])
        self.assertTrue(audit_calls)
        self.assertTrue(reply["guard"]["passed"], reply)
        self.assertIn("semantic_grounded_claims", reply["advisory_audit"]["issues"])
        self.assertFalse(reply["advisory_audit"]["can_override_mandatory"])

    def test_passing_semantic_verdict_cannot_change_parallel_action_binding(self):
        _, contract = prepared(
            "Please assess 420 work vests with genuine licensed reflective material. "
            "Review material rights first and assess rough construction costs only subject to that verification.")
        self.assertTrue(contract["judgment"]["parallel_reversible_advances"])
        language = {"answers": [], "primary_move": "I will verify the licensed material rights and sourcing route.",
                    "parallel_moves": ["A rough construction cost review can proceed subject to material route verification."],
                    "questions": [q.get("text") or q["question"] for q in contract["permitted_questions"]]}
        proposal = normalize_proposal(language, contract)
        self.assertEqual(proposal["parallel_moves"][0]["action"], "INTERNAL_COSTING")
        proposal["parallel_moves"][0]["action"] = "INTERNAL_VERIFICATION"
        guard = validate_proposal(proposal, contract, semantic_review=passing_receipt(proposal, contract))
        self.assertFalse(guard["passed"])
        self.assertTrue(any("parallel" in issue for issue in guard["issues"]), guard)


if __name__ == "__main__":
    unittest.main()
