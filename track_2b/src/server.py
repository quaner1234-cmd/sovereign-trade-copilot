# -*- coding: utf-8 -*-
"""Track 2B HTTP server (stdlib only).
GET  /health  -> {"status":"ok","mode":"llm"|"demo","pipeline":"v3"|"v2","model":...}
POST /process {"email": "..."} -> classification + extraction + draft + validation
                 plus, on v3, the validated fact store with per-fact provenance.
PIPELINE_VERSION selects the pipeline; default is v3 (evidence-gated).
"""
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
import llm_client

PIPELINE_VERSION = os.environ.get("PIPELINE_VERSION", "v3").lower()
if PIPELINE_VERSION == "v3":
    import pipeline_v3 as pipeline
else:
    import pipeline


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok",
                             "mode": "demo" if llm_client.demo_mode() else "llm",
                             "pipeline": PIPELINE_VERSION,
                             "model": llm_client.CONFIG["model"] or "(demo)"})
        else:
            self._send(404, {"error": "not found", "hint": "GET /health or POST /process"})

    def do_POST(self):
        if self.path != "/process":
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "invalid json"})
        email = (body.get("email") or "").strip()
        if not email:
            return self._send(400, {"error": "field 'email' is required"})
        try:
            result = pipeline.process(email)
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})
        self._send(200, result)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"track2b listening on 0.0.0.0:{port} "
          f"(mode={'demo' if llm_client.demo_mode() else 'llm'}, pipeline={PIPELINE_VERSION})",
          flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
