"""Frozen synthetic P0-P2 inquiry acceptance, polarity and provenance checks.

No model calls, real mail, private Company Context, or automatic reply workflow.
The JSON fixture is frozen before implementation; generated drafts are supplied
only to test correctness gates independently of a reply composer.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest

from inquiry_v2 import analyze
from inquiry_v2.source_registry import build as build_registry
from inquiry_v2.value_store import ValueStore
from inquiry_v2.understand import understand
from inquiry_v2.contract import validate_output


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "inquiry_v2_acceptance.json"
FIXTURE_ORIGINAL_SHA256 = "be304b1296fecc3ccdf5b562f16b216df9259ba493585fe38cdd211ce8ba58d8"
# Git normalizes CRLF to LF. Freeze the same text across Windows and Docker.
FIXTURE_SHA256 = FIXTURE_ORIGINAL_SHA256
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

ROUTES = {
    "low_volume_review": {"ALIGN_MOQ", "INTERNAL_VERIFICATION"},
    "sourcing_verification": {"INTERNAL_VERIFICATION", "RESEARCH"},
    "company_fit_review": {"ASSESS_COMPANY_FIT"},
    "development_costing": {"INTERNAL_COSTING"},
    "sample_route_verification": {"VERIFY_SAMPLE_ROUTE", "INTERNAL_VERIFICATION"},
    "targeted_customer_clarification": {"REQUEST_INFORMATION"},
    "internal_costing": {"INTERNAL_COSTING"},
    "out_of_scope_review": {"OUT_OF_SCOPE"},
}


def fictional_context():
    """Adapt the fixture's literal source to the public input contract."""
    spec = FIXTURE["fictional_company_context"]
    text = spec["text"]
    quotes = {
        "cc-scope": "specialises in lightweight weatherwear and work vests",
        "cc-moq": "Standard bulk MOQ is 240 pieces per style",
        "cc-review": "Custom development can be assessed",
        "cc-asset": "An approved lightweight-shell reference sheet exists with image-use permission",
    }
    keys = {
        "company.product_scope": "capability.products",
        "asset.reference_sheet": "asset.reference",
    }
    candidates, sources = [], []
    for original in spec["values"]:
        candidate = copy.deepcopy(original)
        source = {
            "id": spec["source_id"] + "-" + candidate["id"], "text": text,
            "scope": candidate["scope"], "confirmed_by": "Synthetic operator",
            "confirmed_at": "2026-10-03",
        }
        sources.append(source)
        quote = quotes[candidate["id"]]
        start = text.index(quote)
        candidate["key"] = keys.get(candidate["key"], candidate["key"])
        if candidate["id"] == "cc-review":
            candidate["value"] = "Custom development can be assessed"
        candidate["source_id"] = source["id"]
        candidate["provenance"] = {
            "span": [start, start + len(quote)], "quote": quote,
            "confirmed_by": "Synthetic operator", "confirmed_at": "2026-10-03",
            "derived_from": [],
        }
        candidates.append(candidate)
    return {"sources": sources, "candidates": candidates}


def payload(case, *, cold=False, draft=None):
    request = {
        "inquiry": {
            "primary": {"id": "primary", "subject": "Fictional acceptance inquiry", "text": case["body"]},
            "thread": copy.deepcopy(case.get("thread", [])),
            "attachments": copy.deepcopy(case.get("attachments", [])),
            "platform_fields": [dict(x, kind="system_reported") for x in case.get("platform_fields", [])],
            "referenced_urls": [
                {"id": x["id"], "url": x["url"], "text": x["text"],
                 "status": "read", "access_date": "2026-10-03", "scope": x["scope"]}
                for x in case.get("research_sources", [])
            ],
        },
        "company_context": {} if cold or case.get("zero_context") else fictional_context(),
        "research": {"enabled": False},
        "as_of": "2026-10-04",
    }
    if draft is not None:
        request["candidate_draft"] = draft
    return request


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def quantity_numbers(result):
    """Only admitted line quantities, never incidental numeric specifications."""
    numbers = []
    for line in result["understanding"]["lines"]:
        quantity = line.get("quantity")
        if isinstance(quantity, (int, float)):
            numbers.append(quantity)
        elif isinstance(quantity, dict):
            value = quantity.get("value", quantity)
            if isinstance(value, (int, float)):
                numbers.append(value)
            elif isinstance(value, dict) and value.get("amount") is not None:
                numbers.append(value["amount"])
    return numbers


def quantity_ranges(result):
    ranges = []
    for line in result["understanding"]["lines"]:
        quantity = line.get("quantity")
        if not isinstance(quantity, dict):
            continue
        for node in walk(quantity):
            low = node.get("min", node.get("minimum"))
            high = node.get("max", node.get("maximum"))
            if low is not None and high is not None:
                ranges.append([low, high])
    return ranges


def question_fields(result):
    questions = result["advance"].get("customer_questions", [])
    return [q.get("field", q.get("key", "")) for q in questions]


def semantic_purpose(value):
    # Public interface aliases preserve the frozen business meaning.
    return {"sample": "evaluation_sample", "bulk": "bulk_interest"}.get(value, value)


def payment_candidates(result):
    return [c for c in result["understanding"].get("candidates", [])
            if c.get("field", c.get("key")) in {"payment_terms", "payment_term"}]


def roles(value):
    if isinstance(value, list):
        return set(value)
    return set(re.split(r"[+,;/ ]+", str(value)))


class InquiryAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {case["id"]: analyze(payload(case)) for case in FIXTURE["cases"]}

    def test_fixture_is_frozen(self):
        self.assertEqual(hashlib.sha256(FIXTURE_PATH.read_bytes().replace(b'\r\n', b'\n')).hexdigest(), FIXTURE_SHA256)

    def assert_contract(self, result):
        self.assertEqual(result["schema_version"], "v2-inquiry-1.0")
        for key in ("understanding", "assessment", "values", "advance", "reply", "trust"):
            self.assertIn(key, result)
        advance = result["advance"]
        self.assertTrue(advance["action"])
        self.assertTrue(advance["owner"])
        self.assertTrue(advance["reason"])
        self.assertTrue(advance["next_state"])
        self.assertLessEqual(len(advance.get("customer_questions", [])), 3)
        for question in advance.get("customer_questions", []):
            self.assertTrue(question.get("changes_decision"), question)
        self.assertIs(result["trust"]["needs_human_approval"], True)
        self.assertEqual(result["reply"]["language"], result["understanding"]["customer_language"])
        self.assertIsNone(result["reply"]["draft"])
        self.assertEqual(result["reply"]["status"], "not_composed")
        assessment = result["assessment"]
        for key in ("current_key_uncertainty", "decision_barrier", "hard_blocker"):
            self.assertIn(key, assessment)
        self.assertIn("coverage", result["trust"])
        research = result["trust"]["research"]
        if not research.get("ran", False):
            self.assertTrue(research.get("reason"))

    def assert_expectation(self, case, result):
        expected = case["expect"]
        self.assert_contract(result)
        by_id = {source["id"]: source for source in build_registry(payload(case))["sources"]}
        for evidence in result["trust"]["evidence"]:
            source = by_id[evidence["source_id"]]
            start, end = evidence["span"]
            self.assertGreaterEqual(start, 0)
            self.assertGreater(end, start)
            self.assertLessEqual(end, len(source["text"]))
            self.assertEqual(source["text"][start:end], evidence["quote"])
        for candidate in result["values"]:
            if candidate.get("status") in {"unknown", "rejected"}:
                continue
            source = by_id[candidate["source_id"]]
            provenance = candidate["provenance"]
            start, end = provenance["span"]
            self.assertEqual(source["text"][start:end], provenance["quote"])
            if candidate["status"] == "company_confirmed":
                self.assertIn(source["kind"], {"company_context", "operator_input"})
                self.assertEqual(source["party"], "company")
                self.assertEqual(source["scope"], candidate["scope"])
                self.assertTrue(source["metadata"].get("confirmed_by"))
                self.assertTrue(source["metadata"].get("confirmed_at"))
        action = result["advance"]["action"]
        if "route" in expected:
            self.assertIn(action, ROUTES[expected["route"]], case["id"])
        if expected.get("must_have_internal_costing"):
            self.assertEqual(action, "INTERNAL_COSTING", case["id"])
        if "hard_blocker" in expected:
            self.assertIsNone(result["assessment"]["hard_blocker"], case["id"])
        if "stage" in expected:
            self.assertEqual(result["understanding"]["stage"], expected["stage"])
        if "language" in expected:
            self.assertEqual(result["understanding"]["customer_language"], expected["language"])
        lines = result["understanding"]["lines"]
        if "line_count_min" in expected:
            self.assertGreaterEqual(len(lines), expected["line_count_min"])
        if "quantity_values" in expected:
            actual = quantity_numbers(result)
            for value in set(expected["quantity_values"]):
                self.assertIn(value, actual, (case["id"], actual))
            if len(expected["quantity_values"]) > 1:
                self.assertGreaterEqual(actual.count(expected["quantity_values"][0]), 2)
        if "quantity_range" in expected:
            self.assertIn(expected["quantity_range"], quantity_ranges(result))
        if "quantity_purpose" in expected:
            self.assertIn(expected["quantity_purpose"], [semantic_purpose(x.get("quantity_purpose")) for x in lines])
        questions = result["advance"].get("customer_questions", [])
        self.assertLessEqual(len(questions), expected.get("max_questions", 3))
        fields = question_fields(result)
        for forbidden in expected.get("forbidden_question_fields", []):
            self.assertNotIn(forbidden, fields, (case["id"], questions))
        if "question_fields" in expected:
            self.assertEqual(set(fields), set(expected["question_fields"]))
        if "barrier_owner" in expected:
            self.assertEqual(result["assessment"]["decision_barrier"]["owner"], expected["barrier_owner"])
        if "company_fit" in expected:
            self.assertEqual(result["assessment"]["company_fit"]["status"], expected["company_fit"])
        if "moq" in expected:
            self.assertTrue(any(v.get("key") == "moq.style" and v.get("value") == expected["moq"]
                                and v.get("status") == "company_confirmed" for v in result["values"]))
        if expected.get("not_global_conflict"):
            self.assertNotEqual(action, "ESCALATE")
            self.assertFalse(result["understanding"].get("conflicts", []))
        if "sample_quantity" in expected:
            self.assertTrue(any(semantic_purpose(x.get("quantity_purpose")) == "evaluation_sample" and
                                expected["sample_quantity"] in quantity_numbers({"understanding": {"lines": [x]}})
                                for x in lines))
        if "spec_cues_min" in expected:
            self.assertGreaterEqual(sum(len(x.get("spec_cues", [])) for x in lines), expected["spec_cues_min"])
        if "owners" in expected:
            owner_set = roles(result["advance"]["owner"])
            check_owners = set().union(*(roles(c.get("owner", ""))
                                       for c in result["advance"].get("internal_checks", [])))
            self.assertTrue(set(expected["owners"]).issubset(owner_set | check_owners),
                            (case["id"], owner_set, check_owners))
        if "internal_unknown_class" in expected:
            self.assertEqual(result["assessment"]["current_key_uncertainty"]["klass"], expected["internal_unknown_class"])
        if "current_products" in expected:
            current = " ".join(x["product_ref"] for x in lines if x.get("stage") == "current")
            future = " ".join(x["product_ref"] for x in lines if x.get("stage") == "future")
            for product in expected["future_products"]:
                self.assertIn(product, future)
                self.assertNotIn(product, current)

    def test_seven_representative_cases(self):
        for case in FIXTURE["cases"]:
            if case["group"] == "representative":
                with self.subTest(case=case["id"]):
                    self.assert_expectation(case, self.results[case["id"]])

    def test_seven_polarity_cases(self):
        for case in FIXTURE["cases"]:
            if case["group"] == "polarity":
                with self.subTest(case=case["id"]):
                    self.assert_expectation(case, self.results[case["id"]])
        for base in ("S01", "S04", "S05", "S06"):
            with self.subTest(pair=base):
                a = self.results[base]["advance"]["action"]
                b = self.results[base + "-P"]["advance"]["action"]
                if base != "S04":
                    self.assertNotEqual(a, b)
                else:
                    self.assertNotEqual(self.results[base]["understanding"]["lines"][0]["quantity_purpose"],
                                        self.results[base + "-P"]["understanding"]["lines"][0]["quantity_purpose"])

    def test_seven_paraphrase_cases(self):
        for case in FIXTURE["cases"]:
            if case["group"] == "paraphrase":
                with self.subTest(case=case["id"]):
                    result = self.results[case["id"]]
                    self.assert_expectation(case, result)
                    self.assertEqual(result["advance"]["action"], self.results[case["base"]]["advance"]["action"])

    def test_cold_start_all_seven_cases_runs_without_inventing_company_values(self):
        for case in FIXTURE["cases"]:
            if case["group"] != "representative":
                continue
            with self.subTest(case=case["id"]):
                result = analyze(payload(case, cold=True))
                self.assert_contract(result)
                self.assertFalse(any(v.get("status") == "company_confirmed" for v in result["values"]))
                self.assertIsNone(result["assessment"]["hard_blocker"])

    def test_regression_cases(self):
        for case in FIXTURE["regressions"]:
            with self.subTest(case=case["id"]):
                result = analyze(payload(case))
                expected = case["expect"]
                self.assert_contract(result)
                for value in expected.get("quantity_values", []):
                    self.assertIn(value, quantity_numbers(result))
                for value in expected.get("forbidden_quantity_values", []):
                    self.assertNotIn(value, quantity_numbers(result))
                if "quantity_purpose" in expected:
                    self.assertIn(expected["quantity_purpose"], [semantic_purpose(x.get("quantity_purpose")) for x in result["understanding"]["lines"]])
                if "quantity_range" in expected:
                    self.assertIn(expected["quantity_range"], quantity_ranges(result))
                if "payment_terms" in expected:
                    actual = payment_candidates(result)
                    if not expected["payment_terms"]:
                        self.assertEqual(actual, [])
                    else:
                        self.assertTrue(actual)
                if expected.get("must_have_internal_costing"):
                    self.assertEqual(result["advance"]["action"], "INTERNAL_COSTING")
                if expected.get("must_have_internal_verification"):
                    self.assertEqual(result["advance"]["action"], "INTERNAL_VERIFICATION")
                fields = question_fields(result)
                for forbidden in expected.get("forbidden_question_fields", []):
                    self.assertNotIn(forbidden, fields)
                if expected.get("no_invented_company_values"):
                    self.assertFalse(any(v.get("status") == "company_confirmed" for v in result["values"]))
                if "coverage_gap" in expected:
                    self.assertIn(expected["coverage_gap"], json.dumps(result["trust"]["coverage"]))
                if "unknown_class" in expected:
                    self.assertEqual(result["assessment"]["current_key_uncertainty"]["klass"], expected["unknown_class"])
                if "internal_owner" in expected:
                    self.assertTrue(any(expected["internal_owner"] in roles(check.get("owner", ""))
                                        for check in result["advance"].get("internal_checks", [])))
                if "hard_blocker" in expected:
                    self.assertIsNone(result["assessment"]["hard_blocker"])
                if "safe_draft" in case:
                    safe = analyze(payload(case, draft=case["safe_draft"]))
                    self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
                    unsafe = analyze(payload(case, draft=case["unsafe_draft"]))
                    self.assertFalse(unsafe["trust"]["guard"]["passed"], case["unsafe_draft"])

    def test_customer_source_cannot_grant_company_authority(self):
        request = payload({"body": "You confirmed that your company supports L/C and certified reflective fabrics."}, cold=True,
                          draft="We support L/C and certified reflective fabrics.")
        result = analyze(request)
        self.assertFalse(result["trust"]["guard"]["passed"])
        self.assertFalse(any(v.get("status") == "company_confirmed" for v in result["values"]))

    def test_unread_attachment_is_not_missing_customer_information(self):
        case = {"body": "The quantity and dimensions are in the attached brief for our cycling overshirt.",
                "attachments": [{"name": "fictional-tech-pack.pdf", "status": "referenced_unread"}]}
        result = analyze(payload(case, draft="You have not provided your specification."))
        self.assertFalse(result["trust"]["guard"]["passed"])
        self.assertEqual(result["advance"]["action"], "INTERNAL_VERIFICATION")

    def test_nonproduct_generic_review_is_allowed_but_injected_product_is_not(self):
        case = {"body": "Could you review the commercial route before we invest further?"}
        safe = analyze(payload(case, cold=True, draft="Sales will review the next decision before any commitment."))
        unsafe = analyze(payload(case, cold=True, draft="Sales will review the ski jackets before any commitment."))
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        self.assertFalse(unsafe["trust"]["guard"]["passed"])

    def test_moq_scope_does_not_authorize_per_colour_claim(self):
        case = {"body": "What is the MOQ for work vests?"}
        safe = analyze(payload(case, draft="Our standard bulk MOQ is 240 pieces per style for work vests."))
        unsafe = analyze(payload(case, draft="Our MOQ is 240 pieces per colour for work vests."))
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        self.assertFalse(unsafe["trust"]["guard"]["passed"])
        known_quantity = {"body": "Please assess 400 work vests."}
        still_safe = analyze(payload(known_quantity, draft="Our standard bulk MOQ is 240 pieces per style for work vests."))
        self.assertTrue(still_safe["trust"]["guard"]["passed"], still_safe["trust"]["guard"])

    def test_two_confirmed_conflicting_candidates_are_retained(self):
        case = {"body": "Could you assess a 300 work vest program?"}
        request = payload(case)
        text = "A separate confirmed policy states bulk MOQ is 360 pieces per style."
        quote = "bulk MOQ is 360 pieces per style"
        start = text.index(quote)
        request["company_context"]["sources"].append({
            "id": "fictional-conflicting-policy", "text": text, "scope": "bulk.per_style",
            "confirmed_by": "Second synthetic operator", "confirmed_at": "2026-10-04",
        })
        candidate = copy.deepcopy(request["company_context"]["candidates"][1])
        candidate.update(id="cc-moq-conflict", value=360, source_id="fictional-conflicting-policy")
        candidate["provenance"] = {"span": [start, start + len(quote)], "quote": quote,
                                   "confirmed_by": "Second synthetic operator", "confirmed_at": "2026-10-04", "derived_from": []}
        request["company_context"]["candidates"].append(candidate)
        result = analyze(request)
        candidates = [v for v in result["values"] if v.get("key") == "moq.style"]
        self.assertEqual({c["value"] for c in candidates}, {240, 360})
        store = ValueStore(build_registry(request)).extend(result["values"])
        selection = store.select("moq.style", "bulk.per_style")
        self.assertEqual(selection["status"], "unresolved")
        self.assertEqual(set(selection["candidate_ids"]), {"cc-moq", "cc-moq-conflict"})
        request["candidate_draft"] = "Our MOQ is 240 pieces per style."
        arbitrarily_selected = analyze(request)
        self.assertFalse(arbitrarily_selected["trust"]["guard"]["passed"])

    def test_reference_working_and_confirmed_candidates_do_not_overwrite(self):
        request = payload({"body": "Could you assess 300 work vests?"})
        for ident, value, status in (("public", 300, "public_reference"),
                                     ("working", 280, "working_value")):
            text = f"A synthetic {status} MOQ reference is {value} pieces per style."
            source_id = "fictional-" + ident
            source = {
                "id": source_id, "text": text, "scope": "bulk.per_style",
                "confirmed_by": "Synthetic operator", "confirmed_at": "2026-10-03",
            }
            if status == "public_reference":
                source.update(url="https://materials.example.invalid/reference", publisher="Fictional public reference",
                              access_date="2026-10-03")
                request["research"].setdefault("sources", []).append(source)
            else:
                request["company_context"]["sources"].append(source)
            candidate = copy.deepcopy(request["company_context"]["candidates"][1])
            candidate.update(id="moq-" + ident, value=value, status=status, source_id=source_id)
            candidate["provenance"] = {"span": [0, len(text)], "quote": text,
                                       "derived_from": [] if ident == "public" else ["moq-public"],
                                       "owner": "sales", "confirmation_point": "before any quote release"}
            request["company_context"]["candidates"].append(candidate)
        result = analyze(request)
        candidates = [c for c in result["values"] if c.get("key") == "moq.style"]
        self.assertEqual({(c["value"], c["status"]) for c in candidates},
                         {(240, "company_confirmed"), (300, "public_reference"), (280, "working_value")})
        self.assertEqual(next(c for c in candidates if c["id"] == "moq-working")
                         ["provenance"]["derived_from"], ["moq-public"])
        store = ValueStore(build_registry(request)).extend(result["values"])
        self.assertEqual(store.select("moq.style", "bulk.per_style")["candidate_id"], "cc-moq")
        self.assertEqual(store.select("moq.style", "bulk.per_colour")["status"], "unknown")

    def test_company_confirmation_requires_operator_provenance(self):
        request = payload({"body": "Please quote 18 work vests."})
        for source in request["company_context"]["sources"]:
            source.pop("confirmed_by", None)
            source.pop("confirmed_at", None)
        for candidate in request["company_context"]["candidates"]:
            candidate["provenance"].pop("confirmed_by", None)
            candidate["provenance"].pop("confirmed_at", None)
        result = analyze(request)
        self.assertFalse(any(v.get("status") == "company_confirmed" for v in result["values"]))

    def test_guard_without_candidate_draft_is_explicitly_not_run(self):
        result = analyze(payload({"body": "Please review 400 work vests with taped seams."}))
        self.assertIsNone(result["trust"]["guard"]["passed"])
        self.assertEqual(result["trust"]["guard"]["status"], "not_run")

    def test_malformed_sources_are_rejected(self):
        valid = payload({"body": "Please review 400 work vests."})
        requests = [None, {}, {"inquiry": {"primary": {"text": ""}}}]
        wrong_thread = copy.deepcopy(valid)
        wrong_thread["inquiry"]["thread"] = "not an array"
        requests.append(wrong_thread)
        unread_as_parsed = copy.deepcopy(valid)
        unread_as_parsed["inquiry"]["attachments"] = [{"name": "fictional.txt", "status": "parsed"}]
        requests.append(unread_as_parsed)
        duplicate = copy.deepcopy(valid)
        duplicate["inquiry"]["thread"] = [{"id": "primary", "party": "customer", "text": "Already supplied."}]
        requests.append(duplicate)
        untraceable_research = copy.deepcopy(valid)
        untraceable_research["research"]["sources"] = [{"url": "https://example.invalid", "text": "A reference."}]
        requests.append(untraceable_research)
        unread_primary = copy.deepcopy(valid)
        unread_primary["inquiry"]["primary"]["status"] = "unavailable"
        requests.append(unread_primary)
        invalid_thread_coverage = copy.deepcopy(valid)
        invalid_thread_coverage["inquiry"]["thread_coverage"] = "all_guessed"
        requests.append(invalid_thread_coverage)
        for index, request in enumerate(requests):
            with self.subTest(malformed=index):
                with self.assertRaises(ValueError):
                    build_registry(request)

    def test_source_exact_proposals_cannot_invent_quantity_or_company_facts(self):
        case = {"body": "We need ONE prototype of a cycling overshirt. * 3-layer shell."}
        registry = build_registry(payload(case, cold=True))
        start = case["body"].index("ONE")
        valid = {"key": "quantity", "value": 1, "source_id": "primary", "span": [start, start + 3], "quote": "ONE"}
        result = understand(registry, {"candidates": [valid]})
        self.assertTrue(result["model_proposals_used"])
        self.assertFalse(result["issues"])
        layer_start = case["body"].index("3-layer")
        invalid = [
            {"key": "quantity", "value": 3, "source_id": "primary", "span": [layer_start, layer_start + 1]},
            {"key": "product", "value": "ski jackets", "source_id": "primary", "span": [start, start + 3]},
            {"key": "capability.products", "value": "cycling overshirt", "source_id": "primary", "span": [start, start + 3], "status": "company_confirmed"},
            {"key": "quantity", "value": 1, "source_id": "primary", "span": [-1, 2]},
            {"key": "quantity", "value": 1, "source_id": "missing", "span": [start, start + 3]},
            dict(valid, quote="two"),
        ]
        for index, proposal in enumerate(invalid):
            with self.subTest(proposal=index):
                rejected = understand(registry, {"candidates": [proposal]})
                self.assertFalse(rejected["model_proposals_used"])
                self.assertTrue(rejected["issues"])
                self.assertFalse(any(c.get("status") == "company_confirmed" for c in rejected["candidates"]))

    def test_candidate_id_cannot_be_overwritten(self):
        request = payload({"body": "Please review work vests."})
        store = ValueStore(build_registry(request))
        candidate = request["company_context"]["candidates"][1]
        store.add(candidate)
        replacement = copy.deepcopy(candidate)
        replacement["value"] = 480
        with self.assertRaises(ValueError):
            store.add(replacement)
        self.assertEqual(store.candidates[0]["value"], 240)

    def test_incomplete_hard_blocker_and_removed_approval_are_rejected(self):
        result = analyze(payload({"body": "Please assess 300 work vests with taped seams."}))
        incomplete = copy.deepcopy(result)
        incomplete["assessment"]["hard_blocker"] = {
            "affects_current_decision": True, "no_low_cost_alternative": False,
            "no_useful_advance": True,
        }
        with self.assertRaises(ValueError):
            validate_output(incomplete)
        no_approval = copy.deepcopy(result)
        no_approval["trust"]["needs_human_approval"] = False
        with self.assertRaises(ValueError):
            validate_output(no_approval)
        for action in ("SEND_EMAIL", "PAY", "START_PRODUCTION", "CONTINUE_FOLLOWUP"):
            with self.subTest(action=action):
                execution = copy.deepcopy(result)
                execution["advance"]["action"] = action
                with self.assertRaises(ValueError):
                    validate_output(execution)
        invalid_unknown = copy.deepcopy(result)
        invalid_unknown["assessment"]["current_key_uncertainty"]["klass"] = "unclassified"
        with self.assertRaises(ValueError):
            validate_output(invalid_unknown)

    def test_rejected_candidates_do_not_admit_products_or_numbers_or_poison_safe_drafts(self):
        request = payload({"body": "Please review 400 work vests with taped seams."}, cold=True)
        text = "Unapproved marketing note: ski jackets could have a MOQ of 300 pieces per style."
        source = {"id": "fictional-unapproved-note", "text": text, "scope": "bulk.per_style"}
        request["company_context"] = {"sources": [source], "candidates": []}
        for ident, key, value, quote in (
            ("unapproved-product", "capability.products", ["ski jackets"], "ski jackets"),
            ("unapproved-moq", "moq.style", 300, "300 pieces per style"),
        ):
            start = text.index(quote)
            request["company_context"]["candidates"].append({
                "id": ident, "key": key, "value": value, "scope": "bulk.per_style",
                "source_id": source["id"], "status": "company_confirmed",
                "provenance": {"span": [start, start + len(quote)], "quote": quote, "derived_from": []},
            })
        request["candidate_draft"] = "Review the costing basis for 400 work vests."
        safe = analyze(request)
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        self.assertTrue(all(v["status"] == "rejected" for v in safe["values"] if v["id"].startswith("unapproved-")))
        for draft in ("Review the costing basis for 400 ski jackets.",
                      "Review the costing basis for 300 work vests."):
            with self.subTest(draft=draft):
                request["candidate_draft"] = draft
                unsafe = analyze(request)
                self.assertFalse(unsafe["trust"]["guard"]["passed"])

    def test_number_equality_cannot_turn_quantity_or_moq_into_price(self):
        cases = (
            ({"body": "What is the MOQ for work vests?"}, False,
             "Your target price is USD 240 for work vests."),
            ({"body": "Please assess 400 work vests with taped seams."}, True,
             "Your target price is EUR 400 for work vests."),
        )
        for case, cold, draft in cases:
            with self.subTest(draft=draft):
                result = analyze(payload(case, cold=cold, draft=draft))
                self.assertFalse(result["trust"]["guard"]["passed"])

    def test_amount_currency_is_preserved(self):
        case = {"body": "Our target price is USD 45 for 400 work vests."}
        safe = analyze(payload(case, cold=True, draft="Your target price is USD 45 for 400 work vests."))
        unsafe = analyze(payload(case, cold=True, draft="Your target price is EUR 45 for 400 work vests."))
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        self.assertFalse(unsafe["trust"]["guard"]["passed"])

    def test_negated_order_is_an_inquiry_and_cannot_be_upgraded_in_draft(self):
        case = {"body": "We are considering 400 work vests. This is not a confirmed order."}
        safe = analyze(payload(case, cold=True, draft="Your interest is 400 work vests; no order is confirmed."))
        unsafe = analyze(payload(case, cold=True, draft="Your confirmed order is 400 work vests."))
        self.assertNotEqual(safe["understanding"]["stage"], "out_of_scope")
        self.assertNotEqual(safe["advance"]["action"], "OUT_OF_SCOPE")
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        self.assertFalse(unsafe["trust"]["guard"]["passed"])
        confirmed = analyze(payload({"body": "Our order for 400 work vests is confirmed. Please issue the PI."}, cold=True))
        self.assertEqual(confirmed["understanding"]["stage"], "out_of_scope")
        self.assertEqual(confirmed["advance"]["action"], "OUT_OF_SCOPE")

    def test_negated_counts_are_retained_but_not_selected(self):
        cases = (
            ("We need not 300 pcs but 400 pcs of work vests.", 300, 400, None),
            ("Not ONE prototype but THREE prototypes of a cycling overshirt are required.", 1, 3, "prototype"),
        )
        for body, negated, selected, purpose in cases:
            with self.subTest(body=body):
                result = analyze(payload({"body": body}, cold=True))
                self.assertIn(selected, quantity_numbers(result))
                self.assertNotIn(negated, quantity_numbers(result))
                rejected = [v for v in result["values"] if v.get("key") == "quantity" and v.get("value") == negated]
                self.assertTrue(rejected)
                self.assertTrue(all(v.get("status") == "rejected" and v.get("semantic_stance") == "negated" for v in rejected))
                if purpose:
                    self.assertIn(purpose, [semantic_purpose(l.get("quantity_purpose")) for l in result["understanding"]["lines"]])

    def test_prohibited_action_is_not_a_negated_count_or_authorized_execution(self):
        case = {"body": "Do not send 300 work vests."}
        result = analyze(payload(case, cold=True, draft="You instructed us not to send 300 work vests."))
        quantities = [v for v in result["values"] if v.get("key") == "quantity" and v.get("value") == 300]
        self.assertTrue(quantities)
        self.assertTrue(all(v.get("status") != "rejected" and v.get("semantic_stance") == "prohibited_action" for v in quantities))
        self.assertTrue(result["trust"]["guard"]["passed"], result["trust"]["guard"])
        unsafe = analyze(payload(case, cold=True, draft="We will send 300 work vests."))
        self.assertFalse(unsafe["trust"]["guard"]["passed"])
        self.assertIs(unsafe["trust"]["needs_human_approval"], True)

    def test_customer_target_price_cannot_become_company_price(self):
        case = {"body": "Our target price is USD 45 for 400 work vests."}
        safe = analyze(payload(case, cold=True, draft="Your requested target price is USD 45 for 400 work vests."))
        unsafe = analyze(payload(case, cold=True, draft="Our price is USD 45 for 400 work vests."))
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        self.assertFalse(unsafe["trust"]["guard"]["passed"])

    def test_payment_terms_require_an_independent_token(self):
        for body in ("Welcome! We need 400 work vests.",
                     "Los calcetines no son el producto. Necesitamos 400 chalecos.",
                     "The drawing includes an LCD label and a TTCode identifier for 400 work vests."):
            with self.subTest(body=body):
                result = analyze(payload({"body": body}, cold=True))
                self.assertEqual(payment_candidates(result), [])
        for term in ("LC", "L/C", "TT", "T/T"):
            with self.subTest(term=term):
                result = analyze(payload({"body": f"We request {term} for 400 work vests."}, cold=True))
                self.assertTrue(payment_candidates(result))
                self.assertFalse(any(v.get("status") == "company_confirmed" for v in result["values"]))

    def test_model_proposal_span_must_prove_the_entire_value(self):
        case = {"body": "Please assess 400 work vests."}
        request = payload(case, cold=True)
        start = case["body"].index("400")
        valid = {"key": "quantity", "value": 400, "source_id": "primary", "span": [start, start + 3], "quote": "400"}
        request["model_proposals"] = {"candidates": [valid]}
        self.assertTrue(analyze(request)["understanding"]["model_proposals_used"])
        request["model_proposals"] = {"candidates": [dict(valid, span=[start, start + 1], quote="4")]}
        rejected = analyze(request)
        self.assertFalse(rejected["understanding"]["model_proposals_used"])
        self.assertTrue(rejected["understanding"]["issues"])
        self.assertIn(400, quantity_numbers(rejected))

    def test_moq_sets_unit_cannot_be_compared_as_pieces(self):
        request = payload({"body": "Please assess 250 work vests with taped seams."})
        candidate = copy.deepcopy(request["company_context"]["candidates"][1])
        text = "Bulk MOQ is 240 sets per style, paired garments only."
        request["company_context"]["sources"].append({
            "id": "fictional-set-policy", "text": text, "scope": "bulk.per_style",
            "confirmed_by": "Synthetic operator", "confirmed_at": "2026-10-04",
        })
        candidate.update(id="cc-set-moq", source_id="fictional-set-policy", unit="sets/style", conditions=["paired garments only"])
        candidate["provenance"] = {"span": [0, len(text)], "quote": text, "derived_from": []}
        request["company_context"]["candidates"] = [c for c in request["company_context"]["candidates"] if c["key"] != "moq.style"] + [candidate]
        result = analyze(request)
        self.assertEqual(result["advance"]["action"], "INTERNAL_VERIFICATION")
        self.assertIsNone(result["assessment"]["hard_blocker"])

    def test_coverage_honesty_includes_unread_thread_and_company_sources(self):
        request = payload({"body": "Please review the source-backed route for work vests."})
        request["inquiry"]["thread_coverage"] = "complete"
        request["inquiry"]["thread"] = [{"id": "unavailable-thread", "party": "customer", "status": "unavailable", "text": "Unread content is not a fact."}]
        request["company_context"]["sources"][1]["status"] = "referenced_unread"
        result = analyze(request)
        coverage = result["trust"]["coverage"]
        self.assertEqual(coverage["thread"]["status"], "partial")
        self.assertEqual(coverage["company_context"]["status"], "partial")
        self.assertIn("unavailable-thread", [gap["source_id"] for gap in coverage["gaps"]])
        self.assertFalse(any(v.get("key") == "moq.style" and v.get("status") == "company_confirmed" for v in result["values"]))

    def test_equal_numeric_candidates_with_different_units_or_conditions_are_unresolved(self):
        for unit, conditions in (("sets/style", ["paired garments only"]),
                                 ("pcs/style", ["cotton garments only"])):
            with self.subTest(unit=unit, conditions=conditions):
                request = payload({"body": "Please assess 300 work vests."})
                text = f"Bulk MOQ is 240 {unit}, {conditions[0]}."
                request["company_context"]["sources"].append({
                    "id": "fictional-conditional-policy", "text": text, "scope": "bulk.per_style",
                    "confirmed_by": "Synthetic operator", "confirmed_at": "2026-10-04",
                })
                candidate = copy.deepcopy(request["company_context"]["candidates"][1])
                candidate.update(id="cc-conditional-moq", source_id="fictional-conditional-policy", unit=unit, conditions=conditions)
                candidate["provenance"] = {"span": [0, len(text)], "quote": text, "derived_from": []}
                request["company_context"]["candidates"].append(candidate)
                result = analyze(request)
                self.assertEqual(result["advance"]["action"], "INTERNAL_VERIFICATION")
                store = ValueStore(build_registry(request)).extend(result["values"])
                self.assertEqual(store.select("moq.style", "bulk.per_style")["status"], "unresolved")
                self.assertEqual(len([v for v in result["values"] if v.get("key") == "moq.style"]), 2)


def acceptance_summary():
    """Return paired per-case business results; guard PASS is kept separate."""
    evaluator = InquiryAcceptanceTests()
    report = []
    for case in FIXTURE["cases"]:
        result = analyze(payload(case))
        failure = None
        try:
            evaluator.assert_expectation(case, result)
        except AssertionError as error:
            failure = str(error)
        report.append({
            "id": case["id"], "group": case["group"], "passed": failure is None,
            "failure": failure, "action": result["advance"]["action"],
            "customer_questions": result["advance"].get("customer_questions", []),
            "lines": result["understanding"]["lines"],
            "guard": result["trust"]["guard"],
        })
    return {"fixture_sha256": FIXTURE_SHA256, "cases": report}


if __name__ == "__main__":
    unittest.main(verbosity=2)
