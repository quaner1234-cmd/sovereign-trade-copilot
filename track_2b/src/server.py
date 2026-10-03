# -*- coding: utf-8 -*-
"""Track 2B HTTP server (stdlib only).
GET  /health  -> {"status":"ok","mode":"llm"|"demo","pipeline":"v4"|"v2","model":...}
POST /process {"email": "..."} -> classification + extraction + draft + validation
                 plus, on v4, the validated fact store with per-fact provenance.
POST /judgment -> source-backed next-action advice; human approval required.
PIPELINE_VERSION defaults to v4; v3 is a compatibility alias for v4.
"""
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
import llm_client
import judgment

PIPELINE_VERSION = os.environ.get("PIPELINE_VERSION", "v4").lower()
if PIPELINE_VERSION in ("v3", "v4"):
    import pipeline_v3 as pipeline
    PIPELINE_VERSION = pipeline.VERSION
elif PIPELINE_VERSION == "v2":
    import pipeline
else:
    raise ValueError("PIPELINE_VERSION must be v4, v3 (alias), or v2")


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
            self._send(404, {"error": "not found", "hint": "GET /health, POST /process or POST /judgment"})

    def do_POST(self):
        if self.path not in ("/process", "/judgment"):
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not 0 <= n <= 1_000_000:
                return self._send(413, {"error": "request too large"})
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "invalid json"})
        if not isinstance(body, dict):
            return self._send(400, {"error": "JSON object required"})
        if self.path == "/judgment":
            try:
                return self._send(200, judgment.judge(body))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        email = body.get("email")
        if not isinstance(email, str):
            return self._send(400, {"error": "field 'email' must be a string"})
        email = email.strip()
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
