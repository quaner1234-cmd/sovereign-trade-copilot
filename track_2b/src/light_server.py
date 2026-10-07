"""Final competition entrypoint: ephemeral review, one draft, explicit approval."""
import json
import os
import secrets
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import light_harness as H
import llm_client
import company_import

RECORDS = OrderedDict()
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def send(self, code, value, kind='application/json; charset=utf-8'):
        data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            return self.send(200, {'status': 'ok', 'pipeline': H.VERSION,
                                  'mode': 'recorded_replay' if llm_client.demo_mode() else 'live_apertus',
                                  'model': llm_client.CONFIG['model'] or 'swiss-ai/Apertus-v1.5-70B (recorded)',
                                  'sending_enabled': False})
        if path in ('/', '/ui', '/ui/'):
            return self.send(200, (H.ROOT/'src/ui/light.html').read_bytes(), 'text/html; charset=utf-8')
        if path == '/samples':
            cases = json.loads((H.ROOT/'data/light-demo/cases.json').read_text(encoding='utf-8'))['cases']
            return self.send(200, {'samples': [{k:v for k,v in c.items() if k != 'gold'} for c in cases]})
        return self.send(404, {'error': 'not found', 'hint': 'GET /ui, /health, /samples; POST /process, /approve'})

    def do_POST(self):
        # Same-origin browser writes; no body, inquiry, key or draft is logged.
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        if origin is not None and origin != 'http://' + host:
            return self.send(403, {'error': 'same-origin request required'})
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.send(403, {'error': 'cross-site request denied'})
        path = urlsplit(self.path).path
        if path not in ('/process', '/approve', '/context/import'):
            return self.send(404, {'error': 'not found'})
        try:
            n = int(self.headers.get('Content-Length', '0'))
            limit = 6 * 1024 * 1024 if path == '/context/import' else 512000
            if not 0 < n <= limit:
                return self.send(413, {'error': 'request size invalid'})
            if not self.headers.get('Content-Type', '').startswith('application/json'):
                return self.send(415, {'error': 'application/json required'})
            body = json.loads(self.rfile.read(n))
            if not isinstance(body, dict):
                raise ValueError('JSON object required')
            if path == '/context/import':
                return self.send(200, {'document': company_import.import_source(body)})
            if urlsplit(self.path).path == '/process':
                result = H.process(body)
                if result['status'] == 'draft_for_human_review':
                    draft_id = secrets.token_urlsafe(16)
                    result['draft_id'] = draft_id
                    packet = H.normalize(body)
                    # Retain the actual source coverage for review of later edits.
                    packet['source_state'] = result['brief']['source_state']
                    with LOCK:
                        RECORDS[draft_id] = {'packet': packet, 'original': result, 'approvals': []}
                        while len(RECORDS) > 100:
                            RECORDS.popitem(last=False)
                return self.send(200, result)
            actor, draft = body.get('actor', ''), body.get('draft', '')
            if (body.get('reviewed') is not True or not isinstance(actor, str) or not actor.strip() or
                not isinstance(draft, str) or not draft.strip() or len(draft) > 16000):
                raise ValueError('Explicit review, reviewer name and a nonempty draft are required.')
            with LOCK:
                record = RECORDS.get(body.get('draft_id'))
                if record is None:
                    return self.send(409, {'error': 'Draft expired or unknown; approval was not recorded.'})
                approval = {'approval_id': secrets.token_urlsafe(12), 'actor': actor.strip(),
                            'approved_draft_hash': H.digest(draft), 'input_hash': record['original']['input_hash'],
                            'edited': draft != record['original']['raw_draft'], 'sending_enabled': False,
                            'warnings': H.check_draft(draft, record['packet'])}
                record['approvals'].append(approval)
            return self.send(200, {'status': 'human_approved', **approval})
        except company_import.ImportFailure as error:
            return self.send(400, {'error': str(error)})
        except (ValueError, TypeError, KeyError):
            return self.send(400, {'error': 'Invalid request. Check inquiry, source-backed context and explicit review fields.'})
        except Exception:
            # Never echo provider credentials, local paths or private source text.
            return self.send(503, {'error': 'Request could not be completed; previous draft remains unchanged.'})

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    print('Light Harness: human approval required; no sending integration.', flush=True)
    ThreadingHTTPServer((os.environ.get('BIND_HOST', '0.0.0.0'), int(os.environ.get('PORT', '8000'))), Handler).serve_forever()
