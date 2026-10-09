"""Loopback static server for the isolated synthetic card experiment."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
ASSETS = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/model.mjs': ('model.mjs', 'text/javascript; charset=utf-8'),
    '/app.mjs': ('app.mjs', 'text/javascript; charset=utf-8'),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            data = json.dumps({'status': 'ok', 'mode': 'synthetic_card',
                               'model_calls': 0, 'sending_enabled': False}).encode()
            kind, code = 'application/json', 200
        elif path in ASSETS:
            name, kind = ASSETS[path]
            data, code = (ROOT / name).read_bytes(), 200
        else:
            data, kind, code = b'Not found', 'text/plain', 404
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
                         "connect-src 'none'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8003)
    args = parser.parse_args()
    print(f'Synthetic card only: http://127.0.0.1:{args.port}/', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
