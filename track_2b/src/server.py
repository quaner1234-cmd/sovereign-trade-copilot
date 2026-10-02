# -*- coding: utf-8 -*-
"""Track 2B mini-prototype HTTP server (stdlib only).
GET  /health  -> {"status":"ok","mode":"llm"|"demo"}
POST /process {"email": "..."} -> classification + extraction + draft + validation
"""
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
import llm_client
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
            self._send(200, {"status": "ok", "mode": "demo" if llm_client.demo_mode() else "llm",
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
        result = pipeline.process(email)
        self._send(200, result)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"track2b mini-prototype listening on 0.0.0.0:{port} "
          f"(mode={'demo' if llm_client.demo_mode() else 'llm'})", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
