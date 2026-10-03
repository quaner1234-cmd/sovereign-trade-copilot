"""Synthetic business acceptance and trust-boundary tests, offline only."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from judgment import judge, validate_output

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "judgment" / "cases.json"
CASES = json.loads(DATA.read_text(encoding="utf-8"))["cases"]
SCHEMA = json.loads((ROOT / "docs" / "judgment.schema.json").read_text(encoding="utf-8"))
RESULTS = []


def card_edit(payload, source_id, **values):
    p = copy.deepcopy(payload)
    source = next(s for s in p["sources"] if s["id"] == source_id)
    data = json.loads(source["text"])
    data.update(values)
    source["text"] = json.dumps(data)
    return p


def payload(case_id):
    return copy.deepcopy(next(c["input"] for c in CASES if c["id"] == case_id))


class JudgmentTests(unittest.TestCase):
    def assert_contract(self, result, request):
        self.assertEqual(set(result), set(SCHEMA["required"]))
        self.assertTrue(result["needs_human_approval"])
        self.assertEqual(result["schema_version"], "1.0")
        for field, definition in SCHEMA["properties"].items():
            if "enum" in definition:
                self.assertIn(result[field], definition["enum"])
        self.assertIsInstance(result["reason"], str)
        self.assertTrue(result["reason"])
        sources = {s["id"]: s for s in request["sources"]}
        validate_output(result, sources)
        for fact in result["evidence"]:
            self.assertEqual(set(fact), set(SCHEMA["properties"]["evidence"]["items"]["required"]))
        for item in result["blocking_conditions"]:
            self.assertEqual(set(item), set(SCHEMA["properties"]["blocking_conditions"]["items"]["required"]))

    def test_cases_frozen(self):
        # UTF-8 with LF normalization keeps the freeze portable across Git's CRLF checkout.
        self.assertEqual(hashlib.sha256(DATA.read_text(encoding="utf-8").encode()).hexdigest(), DATA.with_suffix(".sha256").read_text().strip())

    def test_payment_node_before_on_after(self):
        for day, want in (("2026-10-04", "WAIT"), ("2026-10-05", "WAIT"), ("2026-10-06", "RECHECK")):
            p = payload("payment_normal"); p["as_of"] = day
            self.assertEqual(judge(p)["action"], want)

    def test_receipt_is_review_not_execution_and_stale_rechecks(self):
        p = card_edit(payload("payment_normal"), "finance", payment_status="received", payment_checked_at="2026-10-04")
        r = judge(p)
        self.assertEqual(r["action"], "CONTINUE_REVIEW")
        self.assertTrue(r["needs_human_approval"])
        for check in ("2026-10-03", "2026-10-05"):
            self.assertEqual(judge(card_edit(p, "finance", payment_checked_at=check))["action"], "RECHECK")

    def test_customer_receipt_does_not_establish_company_receipt(self):
        p = payload("payment_normal")
        p["sources"].append({"id":"customer_receipt", "party":"customer", "format":"fact_card",
                             "text":json.dumps({"subject":p["subject"], "payment_status":"received"})})
        r = judge(p)
        self.assertEqual(r["action"], "RECHECK")
        claim = next(f for f in r["evidence"] if f["source_id"] == "customer_receipt")
        self.assertEqual((claim["stance"], claim["status"]), ("customer", "unconfirmed"))
        p["sources"] = [p["sources"][-1]]
        self.assertEqual(judge(p)["action"], "REQUEST_CONFIRMATION")

    def test_customer_date_cannot_establish_or_extend_payment_node(self):
        p = payload("payment_normal")
        p["as_of"] = "2026-10-06"
        p["sources"].append({"id":"requested_date", "party":"customer", "format":"fact_card",
                             "text":json.dumps({"subject":p["subject"], "payment_due":"2026-10-20"})})
        r = judge(p)
        self.assertEqual(r["action"], "RECHECK")
        claim = next(f for f in r["evidence"] if f["source_id"] == "requested_date")
        self.assertEqual((claim["stance"], claim["status"]), ("customer", "unconfirmed"))
        source = p["sources"][0]
        data = json.loads(source["text"])
        del data["payment_due"]
        source["text"] = json.dumps(data)
        r = judge(p)
        self.assertEqual(r["action"], "REQUEST_CONFIRMATION")
        self.assertTrue(any(x["field"] == "payment_due" for x in r["blocking_conditions"]))

    def test_unsent_pi_does_not_trigger_customer_chasing(self):
        r = judge(card_edit(payload("payment_normal"), "finance", pi_sent=False))
        self.assertEqual((r["action"], r["owner"]), ("REQUEST_CONFIRMATION", "sales"))
        self.assertIn("PI", r["reason"])

    def test_missing_pi_belongs_to_sales_not_finance(self):
        p=payload("payment_normal");source=p["sources"][0];d=json.loads(source["text"]);del d["pi_sent"]
        source["text"]=json.dumps(d)
        r=judge(p)
        self.assertEqual((r["action"],r["owner"]),("REQUEST_CONFIRMATION","sales"))

    def test_future_pending_record_is_rechecked(self):
        p=card_edit(payload("payment_normal"),"finance",payment_checked_at="2026-10-06")
        self.assertEqual(judge(p)["action"],"RECHECK")

    def test_sample_threshold_and_lower_bound(self):
        p = payload("sample_normal")
        for val, want in ((2,"PASS"),(3,"PASS"),(6,"REWORK")):
            self.assertEqual(judge(card_edit(p, "lab", test_value=val))["action"], want)
        p = card_edit(p, "approved_limit", test_min=1)
        self.assertEqual(judge(card_edit(p, "lab", test_value=0))["action"], "REWORK")
        p = card_edit(p, "approved_limit", test_min=5)
        self.assertEqual(judge(p)["action"], "ESCALATE")

    def test_measurement_dimensions_cannot_be_borrowed_or_mixed(self):
        p = payload("sample_normal")
        lab = p["sources"][0]; values=json.loads(lab["text"]); del values["unit"]
        lab["text"] = json.dumps(values)
        self.assertEqual(judge(p)["action"], "REQUEST_CONFIRMATION")
        p = card_edit(payload("sample_normal"), "lab", unit="fraction")
        self.assertEqual(judge(p)["action"], "ESCALATE")
        p = card_edit(payload("sample_normal"), "lab", metric="fabric_weight")
        self.assertEqual(judge(p)["action"], "ESCALATE")

    def test_equivalent_values_and_units_do_not_create_conflict(self):
        p = card_edit(payload("sample_normal"), "lab", unit="%", test_value=2.0)
        self.assertEqual(judge(p)["action"], "PASS")

    def test_unknown_does_not_block_asking_or_preliminary_costing(self):
        p = payload("inquiry_normal");r=judge(p)
        self.assertEqual(r["action"], "INTERNAL_COSTING")
        self.assertTrue(any(x["field"] == "price_approved" and not x["blocks_current_action"] for x in r["blocking_conditions"]))
        r=judge(payload("inquiry_missing"))
        self.assertEqual(r["action"], "REQUEST_INFORMATION")
        self.assertFalse(any(x["blocks_current_action"] for x in r["blocking_conditions"]))

    def test_targets_and_approximation_remain_customer_facts(self):
        r=judge(payload("inquiry_normal"))
        targets=[f for f in r["evidence"] if f["semantic_role"] == "TARGET"]
        self.assertTrue(targets)
        self.assertTrue(all(f["stance"] == "customer" and f["status"] == "unconfirmed" for f in targets))
        q=next(f for f in r["evidence"] if f["field"] == "quantity_qualifier")
        self.assertEqual(q["value"], "approx")
        self.assertIn("around", q["quote"])

    def test_forged_subject_party_locator_and_approval_rejected(self):
        p = payload("inquiry_normal")
        bad=card_edit(p,"spec",subject="OTHER")
        with self.assertRaises(ValueError):judge(bad)
        bad=card_edit(p,"spec",validated=True)
        with self.assertRaises(ValueError):judge(bad)
        bad=copy.deepcopy(p);bad["sources"][0]["party"]="company"
        with self.assertRaises(ValueError):judge(bad)
        r=judge(p);r["needs_human_approval"]=False
        with self.assertRaises(ValueError):validate_output(r,{s["id"]:s for s in p["sources"]})
        r=judge(p);r["evidence"][0]["span"]=[0,1]
        with self.assertRaises(ValueError):validate_output(r,{s["id"]:s for s in p["sources"]})

    def test_untrusted_lab_quantity_does_not_fill_customer_order(self):
        p=payload("inquiry_normal");p["sources"][0]["text"]="Please quote canvas totes."
        p["sources"].append({"id":"lab_qty","party":"lab","format":"fact_card",
                             "text":json.dumps({"subject":p["subject"],"quantity":500})})
        self.assertEqual(judge(p)["action"], "REQUEST_INFORMATION")

    def test_duplicate_json_keys_and_boolean_measurements_rejected(self):
        p=payload("sample_normal");p["sources"][0]["text"]='{"subject":"SAMPLE-301","test_value":2,"test_value":6}'
        with self.assertRaises(ValueError):judge(p)
        with self.assertRaises(ValueError):judge(card_edit(payload("sample_normal"),"lab",test_value=True))


def case_test(case, variant):
    def test(self):
        p=copy.deepcopy(case["input"])
        if variant:
            for s in p["sources"]:
                if s["format"] == "fact_card":
                    s["text"]=json.dumps(json.loads(s["text"]),sort_keys=True,indent=2)
                else:
                    s["text"]="Could you provide an estimate for canvas totes, about 500 pcs? Target cost USD 3.20. Regards, Maya Rao"
        r=judge(p)
        self.assert_contract(r,p)
        self.assertEqual((r["action"],r["owner"]),(case["expected"]["action"],case["expected"]["owner"]))
        RESULTS.append({"id":case["id"],"variant":"equivalent_wording" if variant else "original","status":"PASS","judgment":r})
    return test


for c in CASES:
    for v in (False,True):
        setattr(JudgmentTests,"test_"+c["id"]+("_paraphrase" if v else ""),case_test(c,v))


if __name__ == "__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(JudgmentTests)
    run=unittest.TextTestRunner(verbosity=2).run(suite)
    out=ROOT/"experiments"/"records"/"judgment-001.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({"tests_run":run.testsRun,"passed":run.wasSuccessful(),"cases_hash":hashlib.sha256(DATA.read_text(encoding="utf-8").encode()).hexdigest(),"cases":RESULTS},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    raise SystemExit(0 if run.wasSuccessful() else 1)
