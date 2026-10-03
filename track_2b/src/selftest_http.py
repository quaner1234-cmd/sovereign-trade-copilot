"""Actual local HTTP contract checks, offline; the v3 alias must report v4."""
import os
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["PIPELINE_VERSION"] = "v3"
import json
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from http.server import HTTPServer
import server


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = HTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.http.server_port)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join()

    def post(self, path, body):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
        return json.load(self.opener.open(req,timeout=5))

    def test_version_alias_and_demo(self):
        health = json.load(self.opener.open(self.url + "/health",timeout=5))
        self.assertEqual((health["mode"],health["pipeline"]),("demo","v4"))
        r=self.post("/process",{"email":"Please quote around 300 pcs ski jackets FOB Qingdao. Our target price is USD 45."})
        self.assertEqual(r["meta"]["pipeline"],"v4")
        self.assertTrue(r["validation"]["guard"]["passed"])

    def test_all_judgment_scenarios_over_http(self):
        cases=json.loads((Path(__file__).parent.parent/"data"/"judgment"/"cases.json").read_text(encoding="utf-8"))["cases"]
        for c in cases:
            with self.subTest(case=c["id"]):
                r=self.post("/judgment",c["input"])
                self.assertEqual((r["action"],r["owner"]),(c["expected"]["action"],c["expected"]["owner"]))
                self.assertTrue(r["needs_human_approval"])

    def test_bad_requests_are_400(self):
        for path,body in (("/process",[]),("/process",{"email":42}),("/process",{"email":""}),("/judgment",{})):
            with self.subTest(path=path,body=body):
                with self.assertRaises(urllib.error.HTTPError) as e:self.post(path,body)
                self.assertEqual(e.exception.code,400)


if __name__ == "__main__":
    unittest.main()
