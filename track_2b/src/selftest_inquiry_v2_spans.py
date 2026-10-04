"""Synthetic exact-quote anchoring and source/type proof regressions, offline."""
import unittest
from unittest.mock import patch

from inquiry_v2.model_proposals import propose
from inquiry_v2.source_registry import build
from inquiry_v2.understand import understand


def run(text, proposal, **source_options):
    registry = build({"inquiry": {"primary": {"id": "primary", "text": text}}, **source_options})
    return understand(registry, {"candidates": [proposal]})


class SpanAlignmentTests(unittest.TestCase):
    def proposal(self, key="quantity", value=400, quote="400", **extra):
        return {"key": key, "value": value, "source_id": "primary", "quote": quote, **extra}

    def assert_rejected(self, result, issue=None):
        self.assertFalse(result["model_proposals_used"])
        self.assertTrue(result["issues"])
        if issue:
            self.assertIn(issue, result["issues"])

    def test_wrong_offsets_are_repaired_only_by_unique_exact_quote(self):
        text = "Please review preliminary costing for 400 work vests."
        result = run(text, self.proposal(span=[16, 18]))
        self.assertTrue(result["model_proposals_used"])
        self.assertEqual(result["issues"], [])
        diagnostic = result["proposal_diagnostics"][0]
        self.assertEqual(diagnostic["alignment"], "unique_exact_quote")
        self.assertEqual(diagnostic["model_span"], [16, 18])
        self.assertEqual(diagnostic["resolved_span"], [38, 41])
        self.assertEqual(diagnostic["typed_proof_span"], [38, 52])

    def test_quote_only_is_the_model_contract(self):
        result = run("Please assess 400 work vests.", self.proposal())
        self.assertTrue(result["model_proposals_used"])
        self.assertEqual(result["proposal_diagnostics"][0]["alignment"], "unique_exact_quote")

    def test_correct_explicit_span_still_works_without_quote(self):
        text = "Please assess 400 work vests."
        start = text.index("400")
        proposal = self.proposal(span=[start, start + 3])
        del proposal["quote"]
        result = run(text, proposal)
        self.assertTrue(result["model_proposals_used"])
        self.assertEqual(result["proposal_diagnostics"][0]["alignment"], "model_span_exact")

    def test_python_unicode_offsets_are_computed_from_exact_text(self):
        text = "¿Puedes revisar " + chr(0x1F9E5) + "? Necesitamos 3,000 chalecos."
        result = run(text, self.proposal(value=3000, quote="3,000", span=[1, 6]))
        self.assertTrue(result["model_proposals_used"])
        start = text.index("3,000")
        self.assertEqual(result["proposal_diagnostics"][0]["resolved_span"], [start, start + 5])

    def test_repeated_quote_with_wrong_or_missing_span_is_ambiguous(self):
        text = "Review 400 work vests and 400 rain jackets."
        for extra in ({}, {"span": [0, 3]}):
            with self.subTest(extra=extra):
                self.assert_rejected(run(text, self.proposal(**extra)), "proposal_ambiguous_quote")

    def test_correct_span_can_disambiguate_a_repeated_quote(self):
        text = "Review 400 work vests and 400 rain jackets."
        start = text.index("400")
        result = run(text, self.proposal(span=[start, start + 3]))
        self.assertTrue(result["model_proposals_used"])
        self.assertEqual(result["proposal_diagnostics"][0]["alignment"], "model_span_exact")

    def test_quote_is_not_fuzzy_case_or_unicode_normalized(self):
        text = "Review 400 work vests."
        for quote in ("400 WORK VESTS", "400  work vests", "400 work waistcoats", "four hundred"):
            with self.subTest(quote=quote):
                self.assert_rejected(run(text, self.proposal(quote=quote)))

    def test_context_quote_retains_the_exact_typed_product_proof(self):
        text = "We need ONE prototype of a cycling overshirt."
        quote = "ONE prototype of a cycling overshirt"
        result = run(text, self.proposal(key="product", value="cycling overshirt", quote=quote, span=[2, 5]))
        self.assertTrue(result["model_proposals_used"])
        proof = result["proposal_diagnostics"][0]["typed_proof_span"]
        self.assertEqual(text[proof[0]:proof[1]], "cycling overshirt")

    def test_entire_numeric_value_must_be_present_not_one_digit(self):
        text = "Review 400 work vests."
        for value, quote in ((400, "4"), (4, "4")):
            with self.subTest(value=value):
                self.assert_rejected(run(text, self.proposal(value=value, quote=quote)))

    def test_quantity_cannot_match_larger_quantity_or_identifier(self):
        for text, quote in (("Review 3000 work vests.", "3000"),
                            ("Review work vests with product code TS-300.", "300")):
            with self.subTest(text=text):
                self.assert_rejected(run(text, self.proposal(value=300, quote=quote)))

    def test_layer_count_is_not_a_quantity_even_after_alignment(self):
        text = "We need ONE prototype of a cycling overshirt. * 3-layer shell."
        self.assert_rejected(run(text, self.proposal(value=3, quote="3", span=[0, 1])))

    def test_range_and_spelled_counts_work_without_loosening_types(self):
        cases = (("Review roughly 160–320 work vests.", {"min": 160, "max": 320}, "roughly 160–320 work vests"),
                 ("Review ONE prototype of a cycling overshirt.", 1, "ONE prototype"))
        for text, value, quote in cases:
            with self.subTest(text=text):
                self.assertTrue(run(text, self.proposal(value=value, quote=quote))["model_proposals_used"])
                self.assert_rejected(run(text, self.proposal(value=str(value), quote=quote)), "proposal_invalid_value_type:quantity")

    def test_boolean_and_malformed_range_are_not_numeric_values(self):
        for value in (True, {"min": 160}, {"min": 160, "max": "320"}):
            with self.subTest(value=value):
                self.assert_rejected(run("Review 160–320 work vests.", self.proposal(value=value, quote="160–320")), "proposal_invalid_value_type:quantity")

    def test_payment_requires_complete_token_and_typed_context(self):
        text = "We request L / C for 400 work vests."
        result = run(text, self.proposal(key="payment_terms", value="L/C", quote="L / C", span=[0, 1]))
        self.assertTrue(result["model_proposals_used"])
        self.assert_rejected(run("Una chaqueta acolchada para una prueba.",
            self.proposal(key="payment_terms", value="LC", quote="lc")))

    def test_customer_source_cannot_propose_company_authority(self):
        text = "You support L/C for work vests."
        result = run(text, self.proposal(key="capability.payment_terms", value="L/C", quote="L/C", status="company_confirmed"))
        self.assert_rejected(result)
        self.assertFalse(any(c["status"] == "company_confirmed" for c in result["candidates"]))

    def test_unknown_source_and_unread_source_never_align_to_primary(self):
        text = "Review 400 work vests."
        for source_id in ("missing", "attachment-0", ["primary"]):
            with self.subTest(source_id=source_id):
                result = understand(build({"inquiry": {
                    "primary": {"id": "primary", "text": text},
                    "attachments": [{"id": "attachment-0", "status": "referenced_unread"}]}}),
                    {"candidates": [self.proposal(source_id=source_id)]})
                self.assert_rejected(result, "proposal_invalid_source_span")

    def test_negated_candidate_cannot_be_re_admitted_by_model(self):
        text = "We need not 300 pcs but 400 pcs of work vests."
        self.assert_rejected(run(text, self.proposal(value=300, quote="300")), "proposal_type_context_rejected:quantity")

    def test_invalid_quote_and_missing_offsets_fail_closed(self):
        for proposal in (self.proposal(quote=""), self.proposal(quote=3),
                         {"key": "quantity", "value": 400, "source_id": "primary", "span": [-1, 2], "provenance": None}):
            with self.subTest(proposal=proposal):
                self.assert_rejected(run("Review 400 work vests.", proposal))

    def test_invalid_key_shape_fails_closed_without_runtime_error(self):
        for key in (None, ["quantity"], {"key": "quantity"}):
            with self.subTest(key=key):
                self.assert_rejected(run("Review 400 work vests.", self.proposal(key=key)))

    def test_model_prompt_requests_exact_quotes_not_offset_guessing(self):
        registry = build({"inquiry": {"primary": {"text": "Review 400 work vests."}}})
        with patch("inquiry_v2.model_proposals.llm_client.chat", return_value=('{"candidates": []}', {"mode": "llm"})) as chat:
            proposals, meta = propose(registry)
        self.assertEqual(proposals, {"candidates": []})
        self.assertEqual(meta["span_contract"], "exact_quote_anchor")
        self.assertIn("Do not guess character offsets", chat.call_args.args[0][0]["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
