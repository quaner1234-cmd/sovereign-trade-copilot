"""Generic source coverage/privacy/security regressions; no real customer data."""
import copy
import json
import socket
import time
import unittest
from unittest.mock import patch

import light_harness as H
import source_reader as R


PNG = b'\x89PNG\r\n\x1a\nsynthetic-test-bytes'
LINK = 'https://images.example.invalid/drawing.png?token=synthetic-access'


class Response:
    def __init__(self, data=PNG, status=200, headers=None):
        self.data, self.status = data, status
        self.headers = {'Content-Type': 'image/png', **(headers or {})}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, size):
        data, self.data = self.data[:size], self.data[size:]
        return data

    read1 = read


class Connection:
    sock = None

    def __init__(self, response):
        self.response, self.requests = response, []

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        pass


class SourceTests(unittest.TestCase):
    def packet(self):
        return H.normalize({'inquiry': 'Please assess this design: ' + LINK,
                            'company_context': [{'statement': 'This project may use the approved unit price.',
                                                 'source': 'Explicit operator confirmation',
                                                 'scope': 'This project only', 'status': 'COMPANY_CONFIRMED'}],
                            'context_authorized': True})

    def enrich(self, packet=None):
        with patch.dict(R.os.environ, {'SOURCE_READ_ENABLED': '1'}), \
             patch.object(R, 'fetch_image', return_value=(PNG, 'image/png')), \
             patch.object(R, 'image_text', return_value='CALM SEA'):
            return R.enrich(packet or self.packet())

    def test_partial_evidence_preserves_company_authority_and_original(self):
        packet = self.packet()
        original = copy.deepcopy(packet)
        result = self.enrich(packet)
        self.assertEqual(packet, original)
        self.assertEqual(result['company_context'], original['company_context'])
        image = result['source_state']['attachments'][0]
        self.assertEqual(image['state'], 'partially_read')
        self.assertEqual(image['read_coverage'], ['visible_text'])
        self.assertEqual(image['visual_understanding'], 'not_verified')
        self.assertEqual(image['extracted_text'], 'CALM SEA')
        self.assertNotIn('synthetic-access', json.dumps(H.messages(result)))
        self.assertNotIn(LINK, json.dumps(H.messages(result)))
        self.assertTrue(H.check_draft('We have reviewed the design.', result))
        self.assertIn('not full visual understanding', H.contextual_hint(result))
        result['source_state']['attachments'][0]['url'] = LINK
        result['company_context'][0]['source'] = 'Operator-confirmed source: ' + LINK
        self.assertNotIn('synthetic-access', json.dumps(H.messages(result)))
        self.assertIn('synthetic-access', json.dumps(result))

    def test_disabled_network_and_failed_read_do_not_block_drafting(self):
        with patch.dict(R.os.environ, {'SOURCE_READ_ENABLED': '0'}), \
             patch.object(R, 'fetch_image') as fetch, \
             patch.object(H.llm_client, 'demo_mode', return_value=False), \
             patch.object(H.llm_client, 'chat', return_value=(json.dumps({'draft':'We can assess the request.','contextual_hint':''}), {})):
            result = H.process(self.packet())
            fetch.assert_not_called()
            self.assertEqual(result['status'], 'draft_for_human_review')
            self.assertEqual(result['brief']['source_state']['attachments'][0]['state'], 'referenced_unread')
        with patch.dict(R.os.environ, {'SOURCE_READ_ENABLED': '1'}), \
             patch.object(R, 'fetch_image', side_effect=R.ReadFailure('http_403')):
            result = R.enrich(self.packet())
            self.assertEqual(result['_linked_sources'][0]['reason'], 'http_403')
            self.assertEqual(result['_linked_sources'][0]['state'], 'referenced_unread')
            self.assertEqual(result['_linked_sources'][0]['retrieval'], 'attempted')
            coverage = H.brief_view(result)['retrieval_coverage']
            self.assertEqual(coverage['linked_sources_attempted'], 1)
            self.assertEqual(coverage['linked_sources_downloaded'], 0)
            self.assertEqual(coverage['linked_sources_with_text'], 0)
        with patch.dict(R.os.environ, {'SOURCE_READ_ENABLED': '1'}), \
             patch.object(R, 'fetch_image', return_value=(PNG, 'image/png')), \
             patch.object(R, 'image_text', side_effect=R.ReadFailure('no_readable_text')):
            result = R.enrich(self.packet())
            self.assertEqual(result['_linked_sources'][0]['retrieval'], 'downloaded')
            self.assertEqual(result['_linked_sources'][0]['state'], 'referenced_unread')
            coverage = H.brief_view(result)['retrieval_coverage']
            self.assertEqual(coverage['linked_sources_downloaded'], 1)
            self.assertEqual(coverage['linked_sources_with_text'], 0)

    def test_read_count_and_no_source_work_before_company_confirmation(self):
        packet = self.packet()
        packet['inquiry'] = ' '.join('https://images.example.invalid/' + str(n) + '.jpg' for n in range(4))
        with patch.dict(R.os.environ, {'SOURCE_READ_ENABLED': '1'}), \
             patch.object(R, 'fetch_image', return_value=(PNG, 'image/png')) as fetch, \
             patch.object(R, 'image_text', return_value='TEXT'):
            result = R.enrich(packet)
            self.assertEqual(fetch.call_count, R.MAX_READS)
            self.assertEqual(result['_linked_sources'][2]['reason'], 'read_limit')
            coverage = H.brief_view(result)['retrieval_coverage']
            self.assertEqual(coverage['linked_references_tracked'], 4)
            self.assertEqual(coverage['linked_sources_attempted'], 2)
            self.assertEqual(coverage['linked_sources_with_text'], 2)
        with patch.object(R, 'enrich') as reader:
            self.assertEqual(H.process(dict(self.packet(), context_authorized=False))['status'], 'confirmation_required')
            reader.assert_not_called()

    def test_public_address_checks_literal_private_mixed_dns_and_bad_urls(self):
        for url in ('http://images.example.invalid/a.jpg', 'https://user:pass@example.invalid/a.jpg',
                    'https://example.invalid:bad/a.jpg', 'https://[invalid/a.jpg'):
            with self.assertRaises(R.ReadFailure):
                R.public_address(url)
        for addresses in (['127.0.0.1'], ['10.0.0.1'], ['::1'], ['8.8.8.8', '192.168.1.1']):
            rows = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, 443)) for a in addresses]
            with patch.object(R.socket, 'getaddrinfo', return_value=rows), self.assertRaises(R.ReadFailure):
                R.public_address('https://images.example.invalid/a.jpg')

    def test_https_fetch_keeps_access_query_but_no_provider_credentials(self):
        connection = Connection(Response())
        with patch.object(R, 'public_address', return_value=(R.urlsplit(LINK), '8.8.8.8')), \
             patch.object(R.http.client, 'HTTPSConnection', return_value=connection):
            data, kind = R.fetch_image(LINK, time.monotonic() + 10)
        self.assertEqual((data, kind), (PNG, 'image/png'))
        args, kwargs = connection.requests[0]
        self.assertIn('token=synthetic-access', args[1])
        self.assertNotIn('Authorization', kwargs['headers'])

    def test_fake_ip_proxy_needs_explicit_host_scope_and_never_allows_private_ip(self):
        def rows(address):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]
        with patch.dict(R.os.environ, {'SOURCE_FAKE_IP_HOSTS': ''}), \
             patch.object(R.socket, 'getaddrinfo', return_value=rows('198.18.0.22')), \
             self.assertRaises(R.ReadFailure):
            R.public_address(LINK)
        with patch.dict(R.os.environ, {'SOURCE_FAKE_IP_HOSTS': 'images.example.invalid'}):
            with patch.object(R.socket, 'getaddrinfo', return_value=rows('198.18.0.22')):
                self.assertEqual(R.public_address(LINK)[1], '198.18.0.22')
            for address in ('127.0.0.1', '192.168.1.20'):
                with patch.object(R.socket, 'getaddrinfo', return_value=rows(address)), self.assertRaises(R.ReadFailure):
                    R.public_address(LINK)

    def test_redirect_is_revalidated_and_oversize_html_fake_image_rejected(self):
        redirect = Connection(Response(status=302, headers={'Location': 'https://127.0.0.1/private.jpg'}))
        with patch.object(R, 'public_address', side_effect=[(R.urlsplit(LINK), '8.8.8.8'),
                                                          R.ReadFailure('non_public_destination')]), \
             patch.object(R.http.client, 'HTTPSConnection', return_value=redirect), \
             self.assertRaisesRegex(R.ReadFailure, 'non_public_destination'):
            R.fetch_image(LINK, time.monotonic() + 10)
        for response, reason in ((Response(headers={'Content-Length': str(R.MAX_BYTES + 1)}), 'image_too_large'),
                                 (Response(headers={'Content-Type': 'text/html'}), 'unsupported_content'),
                                 (Response(data=b'not an image'), 'invalid_image')):
            with patch.object(R, 'public_address', return_value=(R.urlsplit(LINK), '8.8.8.8')), \
                 patch.object(R.http.client, 'HTTPSConnection', return_value=Connection(response)), \
                 self.assertRaisesRegex(R.ReadFailure, reason):
                R.fetch_image(LINK, time.monotonic() + 10)

    def test_input_hash_and_source_coverage_survive_single_drafting_call(self):
        packet = self.packet()
        enriched = self.enrich(packet)
        with patch.object(H.llm_client, 'demo_mode', return_value=False), \
             patch.object(R, 'enrich', return_value=enriched), \
             patch.object(H.llm_client, 'chat', return_value=(json.dumps({'draft':'A first draft.','contextual_hint':''}), {})) as chat:
            result = H.process(packet)
        self.assertEqual(result['input_hash'], H.digest(packet))
        self.assertEqual(result['brief']['source_state'], enriched['source_state'])
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(chat.call_args.kwargs['transport_attempts'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
