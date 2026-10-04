"""Frozen P3 private-context acceptance with synthetic facts only.

Each test uses an external temporary SQLite file. The fixture defines business
outcomes before implementation, while helpers adapt only the public API shape.
No model calls, real Company Context, or reply composer are involved.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from inquiry_v2 import analyze
from inquiry_v2.private_context import ContextStore
from inquiry_v2.scope import scope_token


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "inquiry_v2_context_acceptance.json"
FIXTURE_SHA256 = "f4b8c9d1b7cdb79d5c6c5688fe0dc0542d2e8170bb79a39bb39a26ee614dc745"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def apply_text(*args, **kwargs):
    from inquiry_v2.natural_updates import apply_text as apply
    return apply(*args, **kwargs)


def source_context(example="reference", *, scope="global", ident=None,
                   value=None, unit=None, conditions=None, kind=None, party=None):
    spec = copy.deepcopy(FIXTURE["examples"][example])
    if ident:
        spec["id"] = ident
    if value is not None:
        spec["text"] = spec["text"].replace(str(spec["value"]), str(value))
        spec["quote"] = spec["quote"].replace(str(spec["value"]), str(value))
        spec["value"] = value
    status = spec["status"]
    scope_spec = copy.deepcopy(FIXTURE["scopes"][scope]) if isinstance(scope, str) else copy.deepcopy(scope)
    default_kind = {"public_reference": "public_source", "working_value": "operator_input",
                    "company_confirmed": "company_context"}[status]
    default_party = "public" if status == "public_reference" else "company"
    metadata = {"url": "https://example.invalid/reference", "publisher": "Fictional publisher",
                "access_date": "2026-10-04"} if status == "public_reference" else {}
    if status == "company_confirmed":
        metadata.update(confirmed_by="Synthetic company document", confirmed_at="2026-10-04")
    source = {"id": spec["id"] + "-source", "kind": kind or default_kind,
              "party": party or default_party, "status": "read", "text": spec["text"],
              "scope": "synthetic.scope", "metadata": metadata}
    start = spec["text"].index(spec["quote"])
    provenance = {"span": [start, start + len(spec["quote"])], "quote": spec["quote"],
                  "derived_from": []}
    if status == "working_value":
        provenance.update(derived_from=["reference-moq"], owner="Synthetic sales",
                          confirmation_point="Before making a customer commitment")
    candidate = {"id": spec["id"], "key": spec["key"], "value": spec["value"],
                 "unit": unit or spec["unit"], "status": status, "source_id": source["id"],
                 "scope": source["scope"], "scope_spec": scope_spec, "conditions": conditions or [],
                 "provenance": provenance}
    return {"sources": [source], "candidates": [candidate]}


def current_request(**overrides):
    request = {"product_categories": ["work vest"], "markets": ["EU"],
               "quantity": 300, "conditions": ["standard fabric"]}
    request.update(overrides)
    return request


def history_candidate(view, ident):
    return next(c for c in view["candidates"] if c["id"] == ident)


def stable_candidate(candidate):
    projection_fields = {"active", "applicable", "applicable_line_ids", "preferred", "preferred_line_ids"}
    return {k: copy.deepcopy(v) for k, v in candidate.items() if k not in projection_fields}


def selections(view, key="moq.style"):
    return [s for s in view["selections"] if s["key"] == key]


def chosen_candidates(view, key="moq.style"):
    ids = {s.get("candidate_id") for s in selections(view, key) if s.get("candidate_id")}
    return [c for c in view["candidates"] if c["id"] in ids]


class PrivateContextAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-inquiry-context-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "context.sqlite3"
        self.store = ContextStore(self.path)

    def record_reference(self, **kwargs):
        context = source_context(**kwargs)
        self.store.record(context, authority="reference")
        return context["candidates"][0]["id"]

    def confirm(self, ident, scope="global"):
        spec = FIXTURE["scopes"][scope] if isinstance(scope, str) else scope
        return self.store.confirm(ident, actor="Synthetic human", scope_spec=copy.deepcopy(spec))

    def assert_no_company_truth(self, view):
        self.assertFalse(any(c["status"] == "company_confirmed" for c in view["candidates"]))

    def inquiry_result(self, *, body=None, draft=None, request_context=None, store=None):
        payload = {"inquiry": {"primary": {"text": body or FIXTURE["examples"]["next_inquiry"]}}}
        if draft is not None:
            payload["candidate_draft"] = draft
        if request_context is not None:
            payload["request_context"] = request_context
        return analyze(payload, context_store=store or self.store)

    def test_fixture_is_frozen(self):
        text = FIXTURE_PATH.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(text).hexdigest(), FIXTURE_SHA256)
        self.assertEqual(len(FIXTURE["acceptance"]), 7)

    def test_A1_public_reference_never_automatically_becomes_company_truth(self):
        ident = self.record_reference()
        for request in (None, current_request()):
            with self.subTest(request=request):
                view = self.store.view(request)
                self.assert_no_company_truth(view)
                self.assertEqual(history_candidate(view, ident)["status"], "public_reference")
        reopened = ContextStore(self.path)
        self.assert_no_company_truth(reopened.view(current_request()))

    def test_A2_confirm_is_reusable_after_restart_and_keeps_reference(self):
        ident = self.record_reference(scope="category")
        original = stable_candidate(history_candidate(self.store.view(), ident))
        confirmed = self.confirm(ident, "category")
        self.assertNotEqual(confirmed["candidate_id"], ident)
        reopened = ContextStore(self.path)
        view = reopened.view(current_request())
        selected = chosen_candidates(view)
        self.assertTrue(any(c["id"] == confirmed["candidate_id"] and
                            c["status"] == "company_confirmed" and c["value"] == 240 for c in selected))
        self.assertEqual(stable_candidate(history_candidate(view, ident)), original)
        self.assertTrue(view["resolutions"])
        attested = history_candidate(view, confirmed["candidate_id"])
        self.assertIn(ident, attested["provenance"]["derived_from"])
        source = next(s for s in view["sources"] if s["id"] == attested["source_id"])
        self.assertEqual(source["party"], "company")
        self.assertEqual(source["metadata"]["confirmed_by"], "Synthetic human")

    def test_A3_edit_preserves_old_working_candidate_but_changes_preference(self):
        self.record_reference()
        ident = self.record_reference(example="working")
        original = stable_candidate(history_candidate(self.store.view(), ident))
        edited = self.store.edit(ident, 300, actor="Synthetic human", scope_spec={"global": True},
                                 statement="MOQ 改 300")
        view = self.store.view(current_request())
        self.assertEqual(stable_candidate(history_candidate(view, ident)), original)
        self.assertFalse(history_candidate(view, ident)["active"])
        self.assertEqual(history_candidate(view, edited["candidate_id"])["status"], "company_confirmed")
        self.assertTrue(any(c["value"] == 300 and c["id"] == edited["candidate_id"] for c in chosen_candidates(view)))
        self.assertFalse(any(c["id"] == ident for c in chosen_candidates(view)))
        self.assertIn(ident, history_candidate(view, edited["candidate_id"])["provenance"]["derived_from"])

    def test_A4_project_exception_does_not_pollute_global_default(self):
        global_id = self.record_reference()
        global_confirmed = self.confirm(global_id)
        project_id = self.record_reference(ident="project-reference", scope="project", value=80)
        exception = self.confirm(project_id, "project")
        outside = self.store.view(current_request(project_id="synthetic-project-beta"))
        self.assertFalse(history_candidate(outside, exception["candidate_id"])["applicable"])
        self.assertTrue(any(c["id"] == global_confirmed["candidate_id"] and c["value"] == 240
                            for c in chosen_candidates(outside)))
        missing_project = self.store.view(current_request())
        self.assertFalse(history_candidate(missing_project, exception["candidate_id"])["applicable"])
        inside = self.store.view(current_request(project_id="synthetic-project-alpha"))
        self.assertTrue(history_candidate(inside, exception["candidate_id"])["applicable"])
        self.assertTrue(history_candidate(inside, global_confirmed["candidate_id"])["active"])

    def test_A5_customer_claim_cannot_enter_company_context(self):
        context = source_context("company", kind="customer_email", party="customer")
        context["sources"][0]["text"] = "You support L/C and your MOQ is 300 pieces per style."
        quote = context["candidates"][0]["provenance"]["quote"]
        start = context["sources"][0]["text"].index(quote)
        context["candidates"][0]["provenance"]["span"] = [start, start + len(quote)]
        for authority in ("reference", "trusted_company"):
            with self.subTest(authority=authority):
                before = self.store.view()
                with self.assertRaises(ValueError):
                    self.store.record(context, authority=authority, actor="Synthetic human")
                self.assertEqual(self.store.view(), before)
        inquiry = analyze({"inquiry": {"primary": {"text": "You support L/C. Please assess 300 work vests."}},
                           "candidate_draft": "We support L/C."})
        self.assertFalse(inquiry["trust"]["guard"]["passed"])
        self.assertFalse(any(c["status"] == "company_confirmed" for c in inquiry["values"]))

    def test_A6_independent_confirmed_conflicts_remain_explicitly_unresolved(self):
        self.store.record(source_context("company"), authority="trusted_company", actor="Synthetic importer")
        self.store.record(source_context("company", ident="second-approved-moq", value=400),
                          authority="trusted_company", actor="Synthetic importer")
        view = self.store.view(current_request())
        self.assertEqual(len([c for c in view["candidates"] if c["status"] == "company_confirmed"]), 2)
        unresolved = [s for s in view["unresolved"] if s["key"] == "moq.style"]
        self.assertTrue(unresolved)
        self.assertTrue(all(s["status"] == "unresolved" and not s.get("candidate_id") for s in unresolved))
        self.assertFalse(chosen_candidates(view))

    def test_A7_missing_deleted_context_keeps_zero_context_working(self):
        self.assertEqual(self.store.view()["candidates"], [])
        self.record_reference()
        self.path.unlink()
        reopened = ContextStore(self.path)
        self.assertEqual(reopened.view()["candidates"], [])
        result = analyze({"inquiry": {"primary": {"text": FIXTURE["examples"]["next_inquiry"]}}})
        self.assertTrue(result["advance"]["action"])
        self.assertIsNone(result["assessment"]["hard_blocker"])
        self.assertIs(result["trust"]["needs_human_approval"], True)
        self.assertFalse(any(c["status"] == "company_confirmed" for c in result["values"]))

    def test_confirmed_fact_is_used_by_next_inquiry_and_reply_gate(self):
        ident = self.record_reference(scope="category")
        draft = "Our MOQ is 240 pieces per style for work vests."
        before = self.inquiry_result(draft=draft)
        self.assertFalse(before["trust"]["guard"]["passed"])
        confirmed = self.confirm(ident, "category")
        after = self.inquiry_result(draft=draft, store=ContextStore(self.path))
        self.assertTrue(after["trust"]["guard"]["passed"], after["trust"]["guard"])
        self.assertIn(confirmed["candidate_id"], after["advance"]["value_candidate_ids"])
        self.assertTrue(after["trust"]["company_context"]["loaded"])
        self.assertEqual(after["reply"]["status"], "not_composed")

    def test_edit_changes_next_inquiry_and_old_claim_loses_current_authority(self):
        ident = self.record_reference()
        confirmed = self.confirm(ident)
        before = self.inquiry_result()
        self.assertEqual(before["advance"]["action"], "INTERNAL_COSTING")
        edited = self.store.edit(confirmed["candidate_id"], 300, actor="Synthetic human",
                                 scope_spec={"global": True}, statement="MOQ 改 300")
        after = self.inquiry_result(draft="Our MOQ is 300 pieces per style for work vests.")
        self.assertEqual(after["advance"]["action"], "ALIGN_MOQ")
        self.assertIn(edited["candidate_id"], after["advance"]["value_candidate_ids"])
        self.assertTrue(after["trust"]["guard"]["passed"], after["trust"]["guard"])
        obsolete = self.inquiry_result(draft="Our MOQ is 240 pieces per style for work vests.")
        self.assertFalse(obsolete["trust"]["guard"]["passed"])
        old = next(c for c in after["values"] if c["id"] == confirmed["candidate_id"])
        self.assertFalse(old["active"])
        self.assertEqual(old["value"], 240)

    def test_project_exception_authorizes_only_that_project_reply(self):
        self.store.record(source_context("company"), authority="trusted_company", actor="Synthetic importer")
        project_id = self.record_reference(ident="project-reference", scope="project", value=80)
        self.confirm(project_id, "project")
        draft = "Our MOQ is 80 pieces per style for work vests."
        for project_id in (None, "synthetic-project-beta"):
            with self.subTest(project=project_id):
                request = {} if project_id is None else {"project_id": project_id}
                outside = self.inquiry_result(draft=draft, request_context=request)
                self.assertFalse(outside["trust"]["guard"]["passed"])
                self.assertEqual(outside["advance"]["action"], "ALIGN_MOQ")
        inside = self.inquiry_result(draft=draft, request_context={"project_id": "synthetic-project-alpha"})
        self.assertTrue(inside["trust"]["guard"]["passed"], inside["trust"]["guard"])
        self.assertEqual(inside["advance"]["action"], "INTERNAL_COSTING")

    def test_R11_market_quantity_and_condition_limits_gate_reply_claims(self):
        scope = {"product_categories": ["work vest"], "markets": ["EU"],
                 "quantity_range": {"min": 200, "max": 600, "unit": "pcs"},
                 "conditions": ["standard fabric"]}
        ident = self.record_reference(scope=scope)
        self.confirm(ident, scope)
        draft = "Our MOQ is 240 pieces per style for work vests."
        context = {"markets": ["EU"], "conditions": ["standard fabric"]}
        safe = self.inquiry_result(draft=draft, request_context=context)
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        for body, request in ((None, {}), (None, {"markets": ["US"], "conditions": ["standard fabric"]}),
                              (None, {"markets": ["EU"], "conditions": []}),
                              ("Please assess 190 work vests with taped seams.", context),
                              ("Please assess 650 work vests with taped seams.", context),
                              ("Please assess 250 rain capes with taped seams.", context)):
            with self.subTest(body=body, request=request):
                result = self.inquiry_result(body=body, draft=draft, request_context=request)
                self.assertFalse(result["trust"]["guard"]["passed"])
                self.assertTrue(result["advance"]["action"])
                self.assertIsNone(result["assessment"]["hard_blocker"])

    def test_quantity_scope_does_not_treat_bounds_or_approximation_as_exact(self):
        spec = {"product_categories": ["work vest"], "quantity_range": {"min": 300, "max": 500, "unit": "pcs"}}
        self.store.record(source_context("company", scope=spec), authority="trusted_company", actor="Synthetic importer")
        draft = "Our MOQ is 300 pieces per style for work vests."
        exact = self.inquiry_result(body="Please assess 400 work vests with taped seams.", draft=draft)
        self.assertTrue(exact["trust"]["guard"]["passed"], exact["trust"]["guard"])
        for quantity in ("at least 400", "at most 400", "about 400", "roughly 350–450"):
            with self.subTest(quantity=quantity):
                result = self.inquiry_result(body=f"Please assess {quantity} work vests with taped seams.", draft=draft)
                self.assertFalse(result["trust"]["guard"]["passed"])
                self.assertTrue(result["advance"]["action"])

    def test_open_lower_quantity_scope_accepts_proven_lower_bound(self):
        spec = {"product_categories": ["work vest"], "quantity_range": {"min": 300, "unit": "pcs"}}
        self.store.record(source_context("company", scope=spec), authority="trusted_company", actor="Synthetic importer")
        result = self.inquiry_result(body="Please assess at least 400 work vests with taped seams.",
                                     draft="Our MOQ is 300 pieces per style for work vests.")
        self.assertTrue(result["trust"]["guard"]["passed"], result["trust"]["guard"])

    def test_raw_overlapping_company_rules_are_unresolved_in_current_inquiry(self):
        scopes = ({"product_categories": ["work vest"], "markets": ["EU"]},
                  {"product_categories": ["work vest"], "quantity_range": {"min": 300, "max": 500, "unit": "pcs"}})
        context = {"sources": [], "candidates": []}
        for index, (spec, value) in enumerate(zip(scopes, (300, 500))):
            part = source_context("company", ident="overlapping-company-rule-" + str(index), scope=spec, value=value)
            token = scope_token(spec)
            part["sources"][0]["scope"] = token
            part["candidates"][0]["scope"] = token
            context["sources"].extend(part["sources"])
            context["candidates"].extend(part["candidates"])
        for value in (300, 500):
            with self.subTest(value=value):
                result = analyze({"inquiry": {"primary": {"text": "Please assess 400 work vests with taped seams."}},
                                  "request_context": {"markets": ["EU"]}, "company_context": context,
                                  "candidate_draft": f"Our MOQ is {value} pieces per style for work vests."})
                self.assertFalse(result["trust"]["guard"]["passed"])
                self.assertEqual(result["advance"]["action"], "INTERNAL_VERIFICATION")
                self.assertTrue(any(s["status"] == "unresolved" for s in result["value_selections"]))

    def test_R11_category_rule_cannot_authorize_other_current_line(self):
        ident = self.record_reference(scope="category")
        self.confirm(ident, "category")
        body = "Please assess 250 work vests and 250 cotton tote bags with standard fabric."
        safe = self.inquiry_result(body=body, draft="For work vests, our MOQ is 240 pieces per style.")
        unsafe = self.inquiry_result(body=body, draft="For tote bags, our MOQ is 240 pieces per style.")
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        self.assertFalse(unsafe["trust"]["guard"]["passed"])
        generic = self.inquiry_result(body=body, draft="Our MOQ is 240 pieces per style.")
        self.assertFalse(generic["trust"]["guard"]["passed"])

    def test_R11_payment_claim_stays_bound_to_its_authorized_product(self):
        context = source_context("company", scope="category")
        text, quote = "Approved payment method for work vests is L/C.", "L/C"
        context["sources"][0]["text"] = text
        candidate = context["candidates"][0]
        candidate.update(id="approved-vest-payment", key="payment_terms", value="L/C", unit=None)
        start = text.index(quote)
        candidate["provenance"] = {"span": [start, start + len(quote)], "quote": quote, "derived_from": []}
        self.store.record(context, authority="trusted_company", actor="Synthetic importer")
        body = "Please assess 250 work vests and 250 rain jackets with standard fabric."
        safe = self.inquiry_result(body=body, draft="For work vests, we support L/C.")
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        for draft in ("For rain jackets, we support L/C.", "We support L/C."):
            with self.subTest(draft=draft):
                result = self.inquiry_result(body=body, draft=draft)
                self.assertFalse(result["trust"]["guard"]["passed"])

    def test_negated_trusted_payment_source_cannot_authorize_positive_claim(self):
        for negative, narrow in ((False, False), (True, False), (True, True)):
            with self.subTest(negative=negative, narrow=narrow):
                context = source_context("company", scope="category", ident="payment-polarity-" + str(negative) + str(narrow))
                text = "We do not support L/C for work vests." if negative else "We support L/C for work vests."
                quote = "L/C" if narrow else text
                context["sources"][0]["text"] = text
                candidate = context["candidates"][0]
                candidate.update(key="payment_terms", value="L/C", unit=None)
                start = text.index(quote)
                candidate["provenance"] = {"span": [start, start + len(quote)], "quote": quote, "derived_from": []}
                isolated = ContextStore(Path(self.temp.name) / (candidate["id"] + ".sqlite3"))
                isolated.record(context, authority="trusted_company", actor="Synthetic importer")
                result = self.inquiry_result(draft="We support L/C for work vests.", store=isolated)
                self.assertEqual(result["trust"]["guard"]["passed"], not negative, result["trust"]["guard"])

    def test_caller_runtime_flags_cannot_bypass_explicit_scope(self):
        context = source_context("company", scope="category")
        candidate = context["candidates"][0]
        candidate.update(active=True, applicable=True, preferred=True, applicable_line_ids=["L1"],
                         preferred_line_ids=["L1"], resolution="resolved")
        payload = {"inquiry": {"primary": {"text": "Please assess 250 rain capes with taped seams."}},
                   "company_context": context,
                   "candidate_draft": "Our MOQ is 300 pieces per style for rain capes."}
        result = analyze(payload)
        self.assertFalse(result["trust"]["guard"]["passed"])
        loaded = next(c for c in result["values"] if c["id"] == candidate["id"])
        self.assertFalse(loaded["applicable"])
        self.assertNotEqual(result["advance"]["action"], "ALIGN_MOQ")

    def test_nonobject_company_candidate_is_a_validation_error(self):
        request = {"inquiry": {"primary": {"text": FIXTURE["examples"]["next_inquiry"]}},
                   "company_context": {"sources": [], "candidates": [1]}}
        with self.assertRaises(ValueError):
            analyze(request)

    def test_caller_preference_flags_cannot_hide_independent_conflict(self):
        context = source_context("company")
        other = source_context("company", ident="other-policy", value=400)
        context["sources"].extend(other["sources"])
        context["candidates"].extend(other["candidates"])
        context["candidates"][0].update(preferred=True, active=True)
        context["candidates"][1].update(preferred=False, active=False, applicable=False)
        result = analyze({"inquiry": {"primary": {"text": FIXTURE["examples"]["next_inquiry"]}},
                          "company_context": context,
                          "candidate_draft": "Our MOQ is 300 pieces per style for work vests."})
        self.assertFalse(result["trust"]["guard"]["passed"])
        self.assertEqual(result["advance"]["action"], "INTERNAL_VERIFICATION")
        self.assertTrue(any(s["status"] == "unresolved" for s in result["value_selections"]))

    def test_current_product_rule_cannot_authorize_future_product_claim(self):
        ident = self.record_reference(scope="category")
        self.confirm(ident, "category")
        body = "Please assess 250 work vests. In future we will develop rain jackets."
        safe = self.inquiry_result(body=body, draft="Our MOQ is 240 pieces per style for work vests.")
        unsafe = self.inquiry_result(body=body, draft="Our MOQ is 240 pieces per style for work vests and rain jackets.")
        self.assertTrue(any(line["stage"] == "future" for line in safe["understanding"]["lines"]))
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        self.assertFalse(unsafe["trust"]["guard"]["passed"])

    def test_R12_unresolved_private_truth_cannot_authorize_a_reply(self):
        self.store.record(source_context("company"), authority="trusted_company", actor="Synthetic importer")
        self.store.record(source_context("company", ident="second-approved-moq", value=400),
                          authority="trusted_company", actor="Synthetic importer")
        for value in (300, 400):
            with self.subTest(value=value):
                result = self.inquiry_result(draft=f"Our MOQ is {value} pieces per style for work vests.")
                self.assertFalse(result["trust"]["guard"]["passed"])
                self.assertTrue(result["trust"]["company_context"]["unresolved"])
                self.assertTrue(any(s["status"] == "unresolved" for s in result["value_selections"]))
                self.assertEqual(result["advance"]["action"], "INTERNAL_VERIFICATION")
                self.assertIs(result["trust"]["needs_human_approval"], True)

    def test_configured_but_missing_context_uses_real_zero_context_path(self):
        self.assertFalse(self.path.exists())
        result = self.inquiry_result()
        self.assertEqual(result["advance"]["action"], "INTERNAL_COSTING")
        self.assertFalse(result["trust"]["company_context"]["loaded"])
        self.assertFalse(self.path.exists())
        self.record_reference()
        self.path.unlink()
        after = self.inquiry_result(store=ContextStore(self.path))
        self.assertEqual(after["advance"]["action"], result["advance"]["action"])
        self.assertFalse(after["trust"]["company_context"]["loaded"])
        self.assertFalse(self.path.exists())

    def test_reference_import_cannot_self_declare_company_authority(self):
        before = self.store.view()
        with self.assertRaises(ValueError):
            self.store.record(source_context("company"), authority="reference")
        self.assertEqual(self.store.view(), before)
        with self.assertRaises(ValueError):
            self.store.record(source_context("company"), authority="trusted_company")
        self.assertEqual(self.store.view(), before)

    def test_confirmation_requires_actor_and_explicit_scope(self):
        ident = self.record_reference()
        for arguments in ({"actor": "", "scope_spec": {"global": True}},
                          {"actor": "Synthetic human", "scope_spec": {}},
                          {"actor": "Synthetic human", "scope_spec": {"global": True, "project_id": "p"}}):
            with self.subTest(arguments=arguments):
                before = self.store.view()
                with self.assertRaises(ValueError):
                    self.store.confirm(ident, **arguments)
                self.assertEqual(self.store.view(), before)

    def test_category_market_quantity_and_conditions_require_positive_matches(self):
        scopes = (
            ("category", current_request(), current_request(product_categories=["rain cape"])),
            ("market", current_request(), current_request(markets=["US"])),
            ("quantity", current_request(quantity=200), current_request(quantity=199)),
            ("quantity", current_request(quantity=600), current_request(quantity=601)),
            ("conditional", current_request(), current_request(conditions=[])),
        )
        for index, (scope, match, mismatch) in enumerate(scopes):
            with self.subTest(scope=scope, index=index):
                ident = self.record_reference(ident="scoped-reference-" + str(index), scope=scope)
                confirmed = self.confirm(ident, scope)
                self.assertTrue(history_candidate(self.store.view(match), confirmed["candidate_id"])["applicable"])
                self.assertFalse(history_candidate(self.store.view(mismatch), confirmed["candidate_id"])["applicable"])
                missing = current_request()
                if scope in {"category", "market", "conditional", "quantity"}:
                    missing.pop({"category": "product_categories", "market": "markets",
                                 "conditional": "conditions", "quantity": "quantity"}[scope])
                self.assertFalse(history_candidate(self.store.view(missing), confirmed["candidate_id"])["applicable"])

    def test_unknown_or_partial_quantity_range_cannot_match_restricted_fact(self):
        ident = self.record_reference(scope="quantity")
        confirmed = self.confirm(ident, "quantity")
        for quantity in (None, {"min": 150, "max": 300}, {"min": 300, "max": 650}):
            with self.subTest(quantity=quantity):
                view = self.store.view(current_request(quantity=quantity))
                self.assertFalse(history_candidate(view, confirmed["candidate_id"])["applicable"])

    def test_quantity_scope_requires_compatible_unit(self):
        spec = {"product_categories": ["work vest"], "quantity_range": {"min": 200, "max": 600, "unit": "pcs"}}
        ident = self.record_reference(scope=spec)
        confirmed = self.confirm(ident, spec)
        for unit, expected in (("pcs", True), ("sets", False), (None, False)):
            with self.subTest(unit=unit):
                view = self.store.view(current_request(quantity_unit=unit))
                self.assertEqual(history_candidate(view, confirmed["candidate_id"])["applicable"], expected)

    def test_same_numeric_values_with_different_units_are_unresolved(self):
        self.store.record(source_context("company"), authority="trusted_company", actor="Synthetic importer")
        self.store.record(source_context("company", ident="approved-set-moq", unit="sets/style"),
                          authority="trusted_company", actor="Synthetic importer")
        self.assertTrue(self.store.view(current_request())["unresolved"])
        self.assertFalse(chosen_candidates(self.store.view(current_request())))

    def test_same_numeric_values_with_different_conditions_are_unresolved(self):
        self.store.record(source_context("company"), authority="trusted_company", actor="Synthetic importer")
        self.store.record(source_context("company", ident="approved-cotton-moq", conditions=["cotton garments only"]),
                          authority="trusted_company", actor="Synthetic importer")
        view = self.store.view(current_request())
        self.assertTrue(view["unresolved"])
        self.assertFalse(chosen_candidates(view))

    def test_equal_integer_and_decimal_facts_are_not_false_conflicts(self):
        self.store.record(source_context("company"), authority="trusted_company", actor="Synthetic importer")
        self.store.record(source_context("company", ident="equivalent-decimal-moq", value=300.0),
                          authority="trusted_company", actor="Synthetic importer")
        view = self.store.view(current_request())
        self.assertFalse(view["unresolved"])
        self.assertEqual(len(view["candidates"]), 2)
        self.assertTrue(chosen_candidates(view))

    def test_edit_cannot_change_scope_and_supersede_a_global_fact(self):
        ident = self.record_reference()
        confirmed = self.confirm(ident)
        before = self.store.view()
        with self.assertRaises(ValueError):
            self.store.edit(confirmed["candidate_id"], 80, actor="Synthetic human",
                            scope_spec=FIXTURE["scopes"]["project"], statement="This project only: MOQ 80.")
        self.assertEqual(self.store.view(), before)

    def test_natural_language_two_value_edit_retains_history_and_units(self):
        ident = self.record_reference()
        confirmed = self.confirm(ident)
        original = stable_candidate(history_candidate(self.store.view(), confirmed["candidate_id"]))
        apply_text(self.store, FIXTURE["examples"]["edit_statement"], actor="Synthetic human",
                   scope_spec={"global": True})
        view = self.store.view(current_request())
        self.assertEqual(stable_candidate(history_candidate(view, confirmed["candidate_id"])), original)
        self.assertFalse(history_candidate(view, confirmed["candidate_id"])["active"])
        preferred_moq = chosen_candidates(view)
        self.assertTrue(any(c["value"] == 300 and c["unit"] == "pcs/style" and
                            c["status"] == "company_confirmed" for c in preferred_moq))
        lead = chosen_candidates(view, "lead_time.normal")
        self.assertTrue(any(c["value"] == 100 and c["unit"] == "days" and
                            c["status"] == "company_confirmed" for c in lead))
        self.assertTrue(all(c["key"] != "payment_terms" for c in view["candidates"]))

    def test_normal_lead_edit_does_not_overwrite_sample_lead(self):
        context = source_context("company")
        text, quote = "Approved sample lead time is 25 days.", "25 days"
        context["sources"][0]["text"] = text
        candidate = context["candidates"][0]
        candidate.update(id="approved-sample-lead", key="lead_time.sample", value=25, unit="days")
        start = text.index(quote)
        candidate["provenance"] = {"span": [start, start + len(quote)], "quote": quote, "derived_from": []}
        self.store.record(context, authority="trusted_company", actor="Synthetic importer")
        original = stable_candidate(history_candidate(self.store.view(), candidate["id"]))
        apply_text(self.store, "正常交期 100 天", actor="Synthetic human", scope_spec={"global": True})
        view = self.store.view(current_request())
        self.assertEqual(stable_candidate(history_candidate(view, candidate["id"])), original)
        self.assertTrue(history_candidate(view, candidate["id"])["active"])
        self.assertTrue(any(c["value"] == 25 for c in chosen_candidates(view, "lead_time.sample")))
        self.assertTrue(any(c["value"] == 100 for c in chosen_candidates(view, "lead_time.normal")))

    def test_normal_lead_claim_requires_authorized_normal_fact(self):
        draft = "Our normal lead time is 100 days."
        cold = self.inquiry_result(draft=draft)
        self.assertFalse(cold["trust"]["guard"]["passed"])
        apply_text(self.store, "正常交期 100 天", actor="Synthetic human", scope_spec={"global": True})
        confirmed = self.inquiry_result(draft=draft)
        self.assertTrue(confirmed["trust"]["guard"]["passed"], confirmed["trust"]["guard"])
        unconditional = self.inquiry_result(draft="Our lead time is 100 days.")
        self.assertFalse(unconditional["trust"]["guard"]["passed"])

    def test_sample_lead_cannot_authorize_equal_normal_lead(self):
        context = source_context("company")
        text, quote = "Approved sample lead time is 25 days.", "25 days"
        context["sources"][0]["text"] = text
        candidate = context["candidates"][0]
        candidate.update(id="approved-sample-lead", key="lead_time.sample", value=25, unit="days")
        start = text.index(quote)
        candidate["provenance"] = {"span": [start, start + len(quote)], "quote": quote, "derived_from": []}
        self.store.record(context, authority="trusted_company", actor="Synthetic importer")
        safe = self.inquiry_result(draft="Our sample lead time is 25 days.")
        unsafe = self.inquiry_result(draft="Our normal lead time is 25 days.")
        self.assertTrue(safe["trust"]["guard"]["passed"], safe["trust"]["guard"])
        self.assertFalse(unsafe["trust"]["guard"]["passed"])

    def test_cli_natural_edit_and_new_process_reuse_outside_checkout(self):
        env = os.environ.copy()
        env.update(PYTHONPATH=str(Path(__file__).resolve().parent), PYTHONIOENCODING="utf-8",
                   PYTHONDONTWRITEBYTECODE="1")
        base = [sys.executable, "-m", "inquiry_v2.context_cli", "--store", str(self.path)]
        edited = subprocess.run(base + ["--actor", "Synthetic CLI human", "edit",
                                       FIXTURE["examples"]["edit_statement"], "--global"],
                                cwd=self.temp.name, env=env, capture_output=True, text=True,
                                encoding="utf-8", timeout=20)
        self.assertEqual(edited.returncode, 0, edited.stderr)
        change = json.loads(edited.stdout)
        self.assertEqual(len(change["candidate_ids"]), 2)
        reopened = subprocess.run(base + ["list"], cwd=self.temp.name, env=env, capture_output=True,
                                  text=True, encoding="utf-8", timeout=20)
        self.assertEqual(reopened.returncode, 0, reopened.stderr)
        view = json.loads(reopened.stdout)
        values = {c["key"]: c["value"] for c in view["candidates"]}
        self.assertEqual(values, {"moq.general": 300, "lead_time.normal": 100})
        self.assertTrue(all(c["status"] == "company_confirmed" for c in view["candidates"]))
        self.assertTrue(all(c["provenance"]["quote"] == FIXTURE["examples"]["edit_statement"]
                            for c in view["candidates"]))
        self.assertEqual(len(view["resolutions"]), 1)

    def test_natural_language_invalid_second_change_is_atomic(self):
        ident = self.record_reference()
        self.confirm(ident)
        for text in ("MOQ 改 300，正常交期 -100 天", "MOQ 改 300，支持自动付款", "MOQ 改 300，正常交期 未知 天"):
            with self.subTest(text=text):
                before = self.store.view()
                with self.assertRaises(ValueError):
                    apply_text(self.store, text, actor="Synthetic human", scope_spec={"global": True})
                self.assertEqual(self.store.view(), before)

    def test_unrecognized_natural_language_is_not_guessed(self):
        before = self.store.view()
        with self.assertRaises(ValueError):
            apply_text(self.store, "价格再便宜一点，其他都照旧", actor="Synthetic human", scope_spec={"global": True})
        self.assertEqual(self.store.view(), before)

    def test_natural_language_conflict_requires_explicit_human_target(self):
        self.store.record(source_context("company"), authority="trusted_company", actor="Synthetic importer")
        self.store.record(source_context("company", ident="second-approved-moq", value=400),
                          authority="trusted_company", actor="Synthetic importer")
        before = self.store.view()
        with self.assertRaises(ValueError):
            apply_text(self.store, "MOQ 改 350", actor="Synthetic human", scope_spec={"global": True})
        self.assertEqual(self.store.view(), before)

    def test_explicit_human_adjudication_keeps_both_conflicting_histories(self):
        self.store.record(source_context("company"), authority="trusted_company", actor="Synthetic importer")
        self.store.record(source_context("company", ident="second-approved-moq", value=400),
                          authority="trusted_company", actor="Synthetic importer")
        before = self.store.view(current_request())
        self.assertTrue(before["unresolved"])
        originals = {c["id"]: stable_candidate(c) for c in before["candidates"]}
        apply_text(self.store, "MOQ 改 400", actor="Synthetic human", scope_spec={"global": True},
                   target_ids=["company-moq"])
        after = self.store.view(current_request())
        self.assertFalse(after["unresolved"])
        self.assertEqual(len(after["candidates"]), 3)
        for ident, original in originals.items():
            self.assertEqual(stable_candidate(history_candidate(after, ident)), original)
        self.assertFalse(history_candidate(after, "company-moq")["active"])
        self.assertTrue(all(c["value"] == 400 for c in chosen_candidates(after)))

    def test_invalid_record_batch_does_not_partially_write_history(self):
        context = source_context()
        second = copy.deepcopy(context["candidates"][0])
        second.update(id="bad-second-candidate", source_id="missing-source")
        context["candidates"].append(second)
        before = self.store.view()
        with self.assertRaises(ValueError):
            self.store.record(context, authority="reference")
        self.assertEqual(self.store.view(), before)

    def test_concurrent_first_writes_preserve_all_histories(self):
        self.assertFalse(self.path.exists())
        def write(index):
            store = ContextStore(self.path)
            return store.record(source_context(ident="concurrent-reference-" + str(index)), authority="reference")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write, range(4)))
        view = ContextStore(self.path).view(current_request())
        self.assertEqual(len(results), 4)
        self.assertEqual(len(view["sources"]), 4)
        self.assertEqual(len(view["candidates"]), 4)
        self.assertEqual(len(view["resolutions"]), 4)
        self.assertEqual(len({c["id"] for c in view["candidates"]}), 4)
        self.assertFalse(view["unresolved"])

    def test_existing_candidate_id_cannot_be_rewritten(self):
        self.record_reference()
        before = self.store.view()
        with self.assertRaises(ValueError):
            self.store.record(source_context(value=300), authority="reference")
        self.assertEqual(self.store.view(), before)

    def test_invalid_edit_batch_does_not_partially_write_history(self):
        ident = self.record_reference()
        confirmed = self.confirm(ident)
        changes = [{"key": "moq.style", "value": 300, "candidate_id": confirmed["candidate_id"]},
                   {"key": "lead_time.normal", "value": 99, "unit": "days"}]
        before = self.store.view()
        with self.assertRaises(ValueError):
            self.store.apply_edits(changes, actor="Synthetic human", scope_spec={"global": True},
                                   statement=FIXTURE["examples"]["edit_statement"])
        self.assertEqual(self.store.view(), before)

    def test_original_source_and_supersession_survive_restart(self):
        ident = self.record_reference()
        original_source = copy.deepcopy(self.store.view()["sources"][0])
        confirmed = self.confirm(ident)
        edited = self.store.edit(confirmed["candidate_id"], 300, actor="Synthetic human",
                                 scope_spec={"global": True}, statement="MOQ 改 300")
        before = self.store.view(current_request())
        after = ContextStore(self.path).view(current_request())
        self.assertEqual(before, after)
        self.assertIn(original_source, after["sources"])
        self.assertEqual(len(after["candidates"]), 3)
        self.assertTrue(any(c["id"] == edited["candidate_id"] for c in chosen_candidates(after)))

    def test_persistence_requires_absolute_external_path(self):
        with self.assertRaises(ValueError):
            ContextStore("synthetic-context.sqlite3")
        in_repo = Path(__file__).resolve().parent / "synthetic-context-must-not-exist.sqlite3"
        try:
            with self.assertRaises(ValueError):
                ContextStore(in_repo)
            self.assertFalse(in_repo.exists())
        finally:
            for suffix in ("", "-journal", "-wal", "-shm"):
                path = Path(str(in_repo) + suffix)
                if path.exists():
                    path.unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
