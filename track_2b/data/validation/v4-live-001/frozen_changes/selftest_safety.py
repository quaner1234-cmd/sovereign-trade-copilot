"""Offline fault injection for all final-draft paths; no model calls."""
import json
import unittest
from unittest.mock import patch
import fact_parsers as FP
import fact_store as FS
import pipeline_v3 as P
import semantics as SEM

EMAIL = "Our target price is USD 45 for around 300 pcs TS-201 fleece jackets. We need delivery before Dec 20."


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.parsed = FP.collect(EMAIL)
        self.store, self.ns, _ = FS.build(self.parsed, EMAIL, P._demo_selections(self.parsed))
        self.typed = SEM.build_typed(EMAIL, self.parsed, self.store)

    def test_legacy_fallback_is_not_exempt(self):
        # The first fallback fails; the legacy date assertion also must fail.
        with patch.object(P, "_fallback_reply", side_effect=["我方确认 USD 45。", "交期 Dec 20，届时发货。"]):
            ok, draft, issues, attempts = P.checked_fallback(self.store, self.ns, EMAIL, self.parsed, self.typed)
        self.assertTrue(ok)
        self.assertFalse(issues)
        self.assertEqual([x["passed"] for x in attempts], [False, False, True])
        self.assertEqual(attempts[-1]["template"], "review_only")
        self.assertTrue(P.guard_reply(draft, self.store, EMAIL, self.parsed, self.typed)[0])

    def test_all_fallbacks_rejected_withholds(self):
        with patch.object(P, "guard_reply", return_value=(False, "unsafe", ["forced_failure"])):
            ok, draft, issues, attempts = P.checked_fallback(self.store, self.ns, EMAIL, self.parsed, self.typed)
        self.assertFalse(ok)
        self.assertEqual(draft, "")
        self.assertEqual(len(attempts), 3)

    def test_process_final_flags_follow_full_guard(self):
        def chat(messages, **kw):
            system = messages[0]["content"]
            if system == P.PROMPTS["classify"]["system"]:
                return json.dumps({"intent": "inquiry", "language": "en", "urgency": "normal"}), {}
            if system == P.PROMPTS["select"]["system"]:
                return json.dumps(P._demo_selections(self.parsed)), {}
            return "贵司目标价格 USD 45，我方确认可行。", {}
        with patch.object(P.llm_client, "demo_mode", return_value=False), patch.object(P.llm_client, "chat", side_effect=chat):
            result = P.process(EMAIL)
        self.assertFalse(result["meta"]["guards"]["raw"]["passed"])
        self.assertFalse(result["meta"]["stages"]["retry"]["passed"])
        self.assertTrue(result["validation"]["guard"]["passed"])
        self.assertTrue(P.guard_reply(result["draft"], self.store, EMAIL, self.parsed, self.typed)[0])
        with patch.object(P.llm_client, "demo_mode", return_value=False), patch.object(P.llm_client, "chat", side_effect=chat), \
                patch.object(P, "guard_reply", return_value=(False, "unsafe", ["forced_failure"])):
            result = P.process(EMAIL)
        self.assertEqual(result["draft"], "")
        self.assertFalse(result["validation"]["guard"]["passed"])
        self.assertFalse(result["validation"]["draft"]["ok"])

    def test_demo_is_checked_too(self):
        with patch.object(P, "guard_reply", return_value=(False, "unsafe", ["forced_failure"])):
            result = P._demo(EMAIL)
        self.assertFalse(result["validation"]["guard"]["passed"])
        self.assertEqual(result["draft"], "")


if __name__ == "__main__":
    unittest.main()
