"""Private context HTTP lifecycle and authorization; synthetic temporary data."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import HTTPServer

import server
from selftest_inquiry_v2_context import source_context


class PrivateContextHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = HTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.http.server_port)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="synthetic-context-http-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "context.sqlite3"
        environment = patch.dict(os.environ, {
            "COMPANY_CONTEXT_DB": str(self.path), "COMPANY_CONTEXT_TOKEN": "synthetic-private-token",
            "COMPANY_CONTEXT_ACTOR": "Synthetic authorized operator",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def request(self, path, body=None, *, authorized=True, token=None):
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["Authorization"] = "Bearer " + (token or "synthetic-private-token")
        request = urllib.request.Request(self.url + path, headers=headers,
                                         data=None if body is None else json.dumps(body).encode("utf-8"))
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers

    def inquiry(self, **extra):
        return {"inquiry": {"primary": {"text": "Please assess preliminary costing for 250 work vests with taped seams."}}, **extra}

    def record(self, example="reference", **extra):
        context = source_context(example=example)
        status, result, _ = self.request("/v2/company-context/record", {"context": context, **extra})
        self.assertEqual(status, 200)
        return result["recorded_candidate_ids"][0]

    def test_public_reference_confirm_edit_and_reuse_actual_http(self):
        ident = self.record()
        status, view, headers = self.request("/v2/company-context")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(view["candidates"][0]["status"], "public_reference")
        status, confirmation, _ = self.request("/v2/company-context/confirm", {
            "candidate_id": ident, "scope_spec": {"global": True}})
        self.assertEqual(status, 200)
        status, _, _ = self.request("/v2/company-context/edit", {
            "text": "MOQ 改 300，正常交期 100 天", "scope_spec": {"global": True}})
        self.assertEqual(status, 200)
        status, result, _ = self.request("/v2/inquiry", self.inquiry())
        self.assertEqual(status, 200)
        self.assertEqual(result["advance"]["action"], "ALIGN_MOQ")
        self.assertTrue(result["trust"]["needs_human_approval"])
        status, view, _ = self.request("/v2/company-context")
        old = next(c for c in view["candidates"] if c["id"] == ident)
        confirmed = next(c for c in view["candidates"] if c["id"] == confirmation["candidate_id"])
        self.assertEqual(old["status"], "public_reference")
        self.assertFalse(confirmed["active"])
        self.assertEqual(len(view["candidates"]), 4)
        self.assertTrue(all(event["actor"] == "Synthetic authorized operator" for event in view["resolutions"]))

    def test_anonymous_and_wrong_token_cannot_read_or_mutate(self):
        ident = self.record()
        for authorized, token in ((False, None), (True, "wrong-token")):
            with self.subTest(authorized=authorized):
                status, result, _ = self.request("/v2/company-context", authorized=authorized, token=token)
                self.assertEqual(status, 403)
                self.assertEqual(set(result), {"error"})
                status, _, _ = self.request("/v2/company-context/confirm", {
                    "candidate_id": ident, "scope_spec": {"global": True}}, authorized=authorized, token=token)
                self.assertEqual(status, 403)
        _, view, _ = self.request("/v2/company-context")
        self.assertEqual(len(view["candidates"]), 1)

    def test_anonymous_cannot_inject_company_or_operator_scope(self):
        for extra in ({"company_context": {}}, {"company_context": source_context(example="company")},
                      {"request_context": {"project_id": "synthetic-project"}}):
            status, _, _ = self.request("/v2/inquiry", self.inquiry(**extra), authorized=False)
            self.assertEqual(status, 403)
        self.assertFalse(self.path.exists())

    def test_anonymous_inquiry_never_reuses_private_context(self):
        self.record(example="company", authority="trusted_company")
        status, result, _ = self.request("/v2/inquiry", self.inquiry(), authorized=False)
        self.assertEqual(status, 200)
        self.assertEqual(result["advance"]["action"], "INTERNAL_COSTING")
        self.assertFalse(any(c["status"] == "company_confirmed" for c in result["values"]))
        status, result, _ = self.request("/v2/inquiry", self.inquiry())
        self.assertEqual(status, 200)
        self.assertEqual(result["advance"]["action"], "ALIGN_MOQ")

    def test_missing_configuration_preserves_cold_start_without_file(self):
        for name in ("COMPANY_CONTEXT_DB", "COMPANY_CONTEXT_TOKEN", "COMPANY_CONTEXT_ACTOR"):
            os.environ.pop(name, None)
        status, result, _ = self.request("/v2/inquiry", self.inquiry(), authorized=False)
        self.assertEqual(status, 200)
        self.assertEqual(result["advance"]["action"], "INTERNAL_COSTING")
        status, _, _ = self.request("/v2/company-context", authorized=False)
        self.assertEqual(status, 503)
        self.assertFalse(self.path.exists())

    def test_untrusted_import_and_customer_claim_do_not_learn_company_truth(self):
        for context in (source_context(example="company"),
                        source_context(example="company", kind="customer_email", party="customer")):
            status, _, _ = self.request("/v2/company-context/record", {"context": context})
            self.assertEqual(status, 400)
        _, view, _ = self.request("/v2/company-context")
        self.assertEqual(view["candidates"], [])

    def test_operator_configuration_cannot_be_replaced_by_body(self):
        ident = self.record()
        for override in ({"actor": "Customer"}, {"path": str(self.path)}, {"token": "wrong"}):
            status, _, _ = self.request("/v2/company-context/confirm", {
                "candidate_id": ident, "scope_spec": {"global": True}, **override})
            self.assertEqual(status, 400)
        _, view, _ = self.request("/v2/company-context")
        self.assertEqual(len(view["candidates"]), 1)

    def test_private_errors_never_expose_configured_path_or_token(self):
        os.environ["COMPANY_CONTEXT_DB"] = "relative-sensitive-database-path.sqlite3"
        for path, body in (("/v2/company-context", None), ("/v2/inquiry", self.inquiry()),
                           ("/v2/company-context/record", {"context": source_context()})):
            status, result, _ = self.request(path, body)
            self.assertEqual(status, 503)
            serialized = json.dumps(result)
            self.assertNotIn(os.environ["COMPANY_CONTEXT_DB"], serialized)
            self.assertNotIn(os.environ["COMPANY_CONTEXT_TOKEN"], serialized)
        status, _, _ = self.request("/v2/inquiry", self.inquiry(), authorized=False)
        self.assertEqual(status, 200)

    def test_invalid_structured_edit_is_atomic_over_http(self):
        ident = self.record()
        _, before, _ = self.request("/v2/company-context")
        status, _, _ = self.request("/v2/company-context/edit", {
            "scope_spec": {"global": True}, "statement": "MOQ 300, normal lead time 100 days",
            "changes": [{"candidate_id": ident, "key": "moq.style", "value": 300, "unit": "pcs/style"},
                        {"key": "lead_time.normal", "value": 999, "unit": "days"}]})
        self.assertEqual(status, 400)
        _, after, _ = self.request("/v2/company-context")
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
