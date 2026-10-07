"""Bounded reading of customer-linked image text; never company authorization.

OCR is partial evidence, not visual understanding. No image/URL/token is logged
or persistently cached. Network reads can be disabled for disconnected use.
"""
import copy
import hashlib
import http.client
import ipaddress
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 2 * 1024 * 1024
MAX_READS = 2
READ_BUDGET_SECONDS = 18
URL_PATTERN = re.compile(r'https?://[^\s<>"\']+', re.I)


class ReadFailure(Exception):
    """Public, credential-free reason code."""


def references(text):
    found = []
    for match in URL_PATTERN.finditer(text):
        url = match.group().rstrip('.,;)]}')
        if url not in found:
            found.append(url)
    return found


def public_address(url):
    try:
        parts = urlsplit(url)
        supported = (parts.scheme == 'https' and parts.hostname and not parts.username
                     and not parts.password and parts.port in (None, 443))
    except ValueError:
        raise ReadFailure('unsupported_url') from None
    if not supported:
        raise ReadFailure('unsupported_url')
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(parts.hostname, 443,
                                                          type=socket.SOCK_STREAM)}
    except OSError:
        raise ReadFailure('network_unavailable') from None
    trusted_fake_hosts = {host.strip().lower() for host in
                          os.environ.get('SOURCE_FAKE_IP_HOSTS', '').split(',') if host.strip()}
    # Optional deployment configuration for an existing local Fake-IP proxy.
    # Exact operator-approved hosts only; ordinary private/loopback addresses
    # remain forbidden, including when a hostname is in this list.
    fake_route = (parts.hostname.lower() in trusted_fake_hosts and addresses and
                  all(ipaddress.ip_address(a) in ipaddress.ip_network('198.18.0.0/15')
                      for a in addresses))
    if not addresses or (not fake_route and any(not ipaddress.ip_address(a).is_global for a in addresses)):
        raise ReadFailure('non_public_destination')
    return parts, sorted(addresses)[0]


def fetch_bytes(url, deadline, *, accepted_types, max_bytes, too_large_reason,
                accept_header):
    """Direct HTTPS, pinned checked address, bounded redirects/bytes/time."""
    for _ in range(3):
        parts, address = public_address(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReadFailure('read_timeout')
        connection = http.client.HTTPSConnection(parts.hostname, timeout=min(6, remaining),
                                                  context=ssl.create_default_context())
        # Pin the checked address while retaining the original TLS host/SNI.
        connection._create_connection = lambda target, timeout, *args, **kwargs: socket.create_connection(
            (address, 443), timeout)
        try:
            path = parts.path or '/'
            if parts.query:
                path += '?' + parts.query
            connection.request('GET', path, headers={'Accept': accept_header,
                                                     'User-Agent': 'TradeCopilot-SourceReader/1'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ReadFailure('invalid_redirect')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ReadFailure('http_' + str(response.status))
            kind = response.getheader('Content-Type', '').split(';')[0].strip().lower()
            if kind not in accepted_types:
                raise ReadFailure('unsupported_content')
            size = response.getheader('Content-Length')
            if size and int(size) > max_bytes:
                raise ReadFailure(too_large_reason)
            chunks, total = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReadFailure('read_timeout')
                if connection.sock:
                    connection.sock.settimeout(min(6, remaining))
                chunk = response.read1(min(65536, max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise ReadFailure(too_large_reason)
            data = b''.join(chunks)
            return data, kind, url
        except ReadFailure:
            raise
        except (TimeoutError, socket.timeout):
            raise ReadFailure('read_timeout') from None
        except (OSError, ValueError, http.client.HTTPException):
            raise ReadFailure('network_or_content_error') from None
        finally:
            connection.close()
    raise ReadFailure('redirect_limit')


def fetch_image(url, deadline):
    data, kind, _ = fetch_bytes(url, deadline, accepted_types=('image/jpeg', 'image/png'),
                                max_bytes=MAX_BYTES, too_large_reason='image_too_large',
                                accept_header='image/jpeg,image/png')
    valid = data.startswith(b'\xff\xd8\xff') if kind == 'image/jpeg' else data.startswith(b'\x89PNG\r\n\x1a\n')
    if not valid:
        raise ReadFailure('invalid_image')
    return data, kind


def image_text(data, kind):
    executable = shutil.which('tesseract')
    if not executable:
        raise ReadFailure('local_ocr_unavailable')
    with tempfile.TemporaryDirectory(prefix='inquiry-image-') as folder:
        path = Path(folder) / ('reference.png' if kind == 'image/png' else 'reference.jpg')
        path.write_bytes(data)
        try:
            result = subprocess.run([executable, str(path), 'stdout', '--psm', '11', '-l', 'eng'],
                                    capture_output=True, timeout=5,
                                    env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
        except (OSError, subprocess.TimeoutExpired):
            raise ReadFailure('local_ocr_failed') from None
    if result.returncode:
        raise ReadFailure('local_ocr_failed')
    text = result.stdout.decode('utf-8', 'replace').strip()
    if not text:
        raise ReadFailure('no_readable_text')
    return text[:1600]


def enrich(packet):
    result = copy.deepcopy(packet)
    links = references(packet['inquiry'])
    if not links:
        return result
    enabled = os.environ.get('SOURCE_READ_ENABLED', '1').lower() not in ('0', 'false', 'off')
    deadline = time.monotonic() + READ_BUDGET_SECONDS
    attachments = result['source_state'].setdefault('attachments', [])
    evidence = []
    reads = 0
    for number, url in enumerate(links[:8], 1):
        try:
            is_image = bool(re.search(r'\.(?:jpe?g|png)$', urlsplit(url).path, re.I))
        except ValueError:
            is_image = False
        item = {'name': f'Linked reference {number}', 'state': 'referenced_unread',
                'origin': 'customer_link', 'affects_current_reply': is_image,
                'retrieval': 'not_attempted', 'read_coverage': [],
                'visual_understanding': 'not_verified'}
        evidence.append(item)
        attachments.append(item)
        if not is_image:
            item['reason'] = 'only_jpeg_png_supported'
            continue
        if not enabled:
            item['reason'] = 'network_reading_disabled'
            continue
        if reads >= MAX_READS:
            item['reason'] = 'read_limit'
            continue
        reads += 1
        try:
            data, kind = fetch_image(url, deadline)
            item.update(retrieval='downloaded', byte_count=len(data), content_type=kind,
                        content_sha256=hashlib.sha256(data).hexdigest(),
                        accessed_at=datetime.now(timezone.utc).isoformat())
            item['extracted_text'] = image_text(data, kind)
            item.update(state='partially_read', read_coverage=['visible_text'], method='local_ocr')
        except ReadFailure as error:
            item['reason'] = str(error)
    result['_linked_sources'] = evidence
    return result


def inquiry_for_model(packet):
    """The downloader needs signed URLs; the drafting model does not."""
    text = packet['inquiry']
    for number, url in enumerate(references(text), 1):
        text = text.replace(url, f'[linked reference {number}]')
    return text


def safe_for_model(value):
    """Keep signed source URLs in application evidence, including nested fields."""
    if isinstance(value, str):
        for url in references(value):
            value = value.replace(url, '[source link retained in application]')
        return value
    if isinstance(value, list):
        return [safe_for_model(item) for item in value]
    if isinstance(value, dict):
        return {key: safe_for_model(item) for key, item in value.items()}
    return value
