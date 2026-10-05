# -*- coding: utf-8 -*-
"""Track 2B HTTP server (stdlib only).
GET  /health  -> {"status":"ok","mode":"llm"|"demo","pipeline":"v4"|"v2","model":...}
GET  /ui      -> the operator console (single self-contained page, no external assets)
GET  /samples -> the synthetic demonstration fixtures, for the console's picker
POST /process {"email": "..."} -> classification + extraction + draft + validation
                 plus, on v4, the validated fact store with per-fact provenance.
POST /judgment -> source-backed next-action advice; human approval required.
POST /v2/inquiry -> typed inquiry judgment; generate_reply=true requests a first reply.
GET /v2/company-context -> authenticated private ledger; no public profile.
POST /v2/company-context/{record,confirm,edit} -> authenticated private changes.
PIPELINE_VERSION defaults to v4; v3 is a compatibility alias for v4.
"""
import json, os, sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import llm_client
import judgment
import inquiry_v2
from inquiry_v2.context_service import PrivateContextAccess, PrivateContextError

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES_PATH = os.path.join(os.path.dirname(HERE), "data", "samples.json")

PIPELINE_VERSION = os.environ.get("PIPELINE_VERSION", "v4").lower()
if PIPELINE_VERSION in ("v3", "v4"):
    import pipeline_v3 as pipeline
    PIPELINE_VERSION = pipeline.VERSION
elif PIPELINE_VERSION == "v2":
    import pipeline
else:
    raise ValueError("PIPELINE_VERSION must be v4, v3 (alias), or v2")

UI_PATH = os.path.join(HERE, "ui", "review.html" if PIPELINE_VERSION == "v2" else "index.html")


class Handler(BaseHTTPRequestHandler):
    def _review_access(self):
        # This private prototype is usable only through a loopback origin.
        host=self.headers.get('Host','')
        hostname=urlsplit('http://'+host).hostname
        origin=self.headers.get('Origin')
        if (self.client_address[0] not in ('127.0.0.1','::1') or hostname not in ('127.0.0.1','localhost','::1')
                or origin is not None and origin!='http://'+host
                or self.headers.get('Sec-Fetch-Site')=='cross-site'):
            from inquiry_v2.context_service import PrivateContextError
            raise PrivateContextError(403,'review prototype requires a same-origin loopback request')
        from inquiry_v2.reviewer import Reviewer
        return Reviewer()

    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _send_file(self, path, content_type):
        try:
            with open(path, "rb") as fh:
                b = fh.read()
        except OSError:
            return self._send(404, {"error": "asset not found"})
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path=urlsplit(self.path).path
        if path.startswith('/review/'):
            try:
                service=self._review_access()
                query=parse_qs(urlsplit(self.path).query)
                if path=='/review/cases':result=service.cases()
                elif path=='/review/state':result=service.view(service._get(query['id'][0]))
                elif path=='/review/summary':result=service.summary(query['id'][0])
                else:return self._send(404,{'error':'not found'})
                return self._send(200,result)
            except PrivateContextError as error:
                return self._send(error.status,{'error':str(error)})
            except (ValueError,KeyError,OSError,sqlite3.Error):
                return self._send(503,{'error':'private review configuration or record unavailable'})
        if self.path == "/health":
            self._send(200, {"status": "ok",
                             "mode": "demo" if llm_client.demo_mode() else "llm",
                             "pipeline": PIPELINE_VERSION,
                             "model": llm_client.CONFIG["model"] or "(demo)"})
        elif self.path in ("/ui", "/ui/"):
            self._send_file(UI_PATH, "text/html; charset=utf-8")
        elif self.path == "/samples":
            try:
                with open(SAMPLES_PATH, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                return self._send(500, {"error": "sample fixtures unavailable"})
            self._send(200, {"samples": data.get("samples", [])})
        elif self.path == "/v2/company-context":
            try:
                self._send(200, PrivateContextAccess().view(self.headers))
            except PrivateContextError as error:
                self._send(error.status, {"error": str(error)})
        else:
            self._send(404, {"error": "not found",
                             "hint": "GET /ui, GET /health, GET /samples, POST /process or POST /judgment"})

    def do_POST(self):
        private_actions = {"/v2/company-context/" + action: action for action in ("record", "confirm", "edit")}
        review_actions={'/review/'+v:v for v in ('start','next','act','regenerate','live','finish')}
        if self.path not in ("/process", "/judgment", "/v2/inquiry") and self.path not in private_actions and self.path not in review_actions:
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
        if self.path in review_actions:
            from inquiry_v2.reviewer import ReviewConflict
            try:
                if not self.headers.get('Content-Type','').startswith('application/json'):
                    return self._send(415,{'error':'application/json required'})
                service=self._review_access()
                result=getattr(service,{'next':'next_task','act':'act'}.get(review_actions[self.path],review_actions[self.path]))(body)
                return self._send(200,result)
            except PrivateContextError as error:
                return self._send(error.status,{'error':str(error)})
            except ReviewConflict as error:
                return self._send(409,{'error':str(error)})
            except (ValueError,KeyError) as error:
                return self._send(400,{'error':str(error) if isinstance(error,ValueError) else 'invalid review request'})
            except (OSError,sqlite3.Error):
                return self._send(503,{'error':'private review storage unavailable'})
        if self.path == "/v2/inquiry":
            try:
                return self._send(200, PrivateContextAccess().inquiry(body, self.headers))
            except PrivateContextError as error:
                return self._send(error.status, {"error": str(error)})
        if self.path in private_actions:
            try:
                return self._send(200, PrivateContextAccess().mutate(private_actions[self.path], body, self.headers))
            except PrivateContextError as error:
                return self._send(error.status, {"error": str(error)})
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
    host=os.environ.get('BIND_HOST','0.0.0.0')
    print(f"track2b listening on {host}:{port} "
          f"(mode={'demo' if llm_client.demo_mode() else 'llm'}, pipeline={PIPELINE_VERSION})",
          flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
