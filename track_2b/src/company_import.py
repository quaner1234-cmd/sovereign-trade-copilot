"""Read operator-selected company sources locally. No extraction model or storage."""
import base64
import binascii
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import source_reader as R

MAX_BYTES = 4 * 1024 * 1024
MAX_TEXT = 60000
MAX_PAGES = 30


class ImportFailure(ValueError):
    """Safe message intended for the local reviewer."""


def decode_text(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        encodings = ('utf-16',)
    else:
        encodings = ('utf-8-sig', 'gb18030')
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            if '\x00' not in text:
                return text
        except UnicodeError:
            pass
    raise ImportFailure('Could not decode this text file. Save it as UTF-8 and upload it again.')


def pdf_text(data):
    if not data.startswith(b'%PDF-'):
        raise ImportFailure('The file is not a valid PDF.')
    info, extract = shutil.which('pdfinfo'), shutil.which('pdftotext')
    if not info or not extract:
        raise ImportFailure('Local PDF text reader is unavailable. Upload Markdown or TXT instead.')
    with tempfile.TemporaryDirectory(prefix='company-document-') as folder:
        path, output = Path(folder)/'input.pdf', Path(folder)/'text.txt'
        path.write_bytes(data)
        try:
            metadata = subprocess.run([info, str(path)], capture_output=True, timeout=5,
                                      env={**os.environ, 'LC_ALL': 'C'})
            pages = re.search(rb'^Pages:\s+(\d+)', metadata.stdout, re.M)
            if metadata.returncode or not pages:
                raise ImportFailure('This PDF could not be read. It may be damaged or password-protected.')
            count = int(pages.group(1))
            if count > MAX_PAGES:
                raise ImportFailure('Please upload a PDF of at most 30 pages relevant to this inquiry.')
            result = subprocess.run([extract, '-enc', 'UTF-8', '-layout', str(path), str(output)],
                                    capture_output=True, timeout=8)
            if result.returncode or not output.exists():
                raise ImportFailure('Could not extract text from this PDF.')
            if output.stat().st_size > MAX_TEXT * 4:
                raise ImportFailure('The extracted PDF text is too long. Upload the relevant sections only.')
            text = output.read_text(encoding='utf-8')
        except (OSError, subprocess.TimeoutExpired):
            raise ImportFailure('Local PDF reading failed or timed out. Upload Markdown or TXT instead.') from None
    if not text.strip():
        raise ImportFailure('No text could be extracted. This may be a scanned PDF; upload a text version. It has not been read.')
    return text, count


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head', 'noscript', 'template'):
            self.hidden += 1
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'tr', 'section'):
            self.parts.append('\n')
        elif tag in ('td', 'th'):
            self.parts.append(' | ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head', 'noscript', 'template') and self.hidden:
            self.hidden -= 1
        if tag in ('p', 'div', 'li', 'tr', 'section'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data+' ')

    def text(self):
        return '\n'.join(line.strip() for line in ''.join(self.parts).splitlines() if line.strip())


def import_source(body):
    kind = body.get('kind')
    pages = None
    if kind == 'file':
        name, encoded = body.get('name'), body.get('content_base64')
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ImportFailure('Select a named Markdown, TXT or PDF file.')
        name = name.replace('\\', '/').rsplit('/', 1)[-1]
        suffix = Path(name).suffix.lower()
        if suffix not in ('.md', '.markdown', '.txt', '.pdf'):
            raise ImportFailure('Supported files: Markdown (.md), TXT and text-based PDF.')
        if not isinstance(encoded, str) or len(encoded) > ((MAX_BYTES + 2)//3)*4:
            raise ImportFailure('Each file must be at most 4 MiB.')
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ImportFailure('The upload is invalid. Select the file again.') from None
        if not data or len(data) > MAX_BYTES:
            raise ImportFailure('Select a nonempty file of at most 4 MiB.')
        if suffix == '.pdf':
            text, pages = pdf_text(data)
            coverage = 'Extracted PDF text only; images, diagrams and table layout are not verified.'
            state = 'partially_read'
        else:
            text = decode_text(data)
            coverage, state = 'Full supplied text file.', 'read'
        source = name
        status = 'WORKING_VALUE'
    elif kind == 'website':
        url = body.get('url')
        if not isinstance(url, str) or not url.strip() or len(url) > 2048:
            raise ImportFailure('Enter the specific company webpage URL.')
        if os.environ.get('SOURCE_READ_ENABLED', '1').lower() in ('0', 'false', 'off'):
            raise ImportFailure('Web reading is disabled. Upload a local Markdown, TXT or PDF file instead.')
        url = url.strip()
        if not re.match(r'^https?://', url, re.I):
            url = 'https://' + url
        try:
            data, content_type, source = R.fetch_bytes(url, time.monotonic()+18,
                accepted_types=('text/html', 'application/xhtml+xml', 'text/plain', 'text/markdown', 'application/pdf'),
                max_bytes=MAX_BYTES, too_large_reason='document_too_large',
                accept_header='text/html,text/plain,application/pdf')
        except R.ReadFailure:
            raise ImportFailure('Could not read this public HTTPS page. It may require login, block access or be unreachable. Upload a file instead; existing context is kept.') from None
        if content_type == 'application/pdf':
            text, pages = pdf_text(data)
            coverage = 'PDF text at this URL only; images and other website pages were not read.'
        elif content_type in ('text/html', 'application/xhtml+xml'):
            parser = PageText()
            parser.feed(decode_text(data))
            text = parser.text()
            coverage = 'Static text on this page only; linked pages, images and JavaScript content were not read.'
        else:
            text = decode_text(data)
            coverage = 'Text at this URL only; other pages were not read.'
        state, status = 'partially_read', 'PUBLIC_REFERENCE'
        name = R.urlsplit(source).hostname
    else:
        raise ImportFailure('Choose a file or a website to import.')
    if not text.strip():
        raise ImportFailure('No readable text was found; existing context is kept.')
    if len(text) > MAX_TEXT:
        raise ImportFailure('This source exceeds 60,000 text characters. Upload the relevant sections only; nothing was silently truncated.')
    return {'name': name, 'source': source, 'source_kind': kind, 'text': text,
            'status': status, 'reading_state': state, 'coverage': coverage,
            'pdf_pages': pages, 'sha256': hashlib.sha256(data).hexdigest(),
            'accessed_at': datetime.now(timezone.utc).isoformat()}
