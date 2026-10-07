"""Client failure boundaries with mocked transport; no model or network calls."""
import io
import json
import socket
import unittest
import urllib.error
from unittest.mock import Mock, patch

import llm_client as C


class ClientTests(unittest.TestCase):
    KEY = 'synthetic-client-test-key'
    PRIVATE_URL = 'https://example.invalid/private?token=synthetic-query-token'
    PRIVATE_BODY = 'synthetic-private-provider-body'

    def setUp(self):
        self.config = patch.dict(C.CONFIG, model='synthetic-test-model',
                                 base_url='https://example.invalid/v1',
                                 api_key=self.KEY, timeout_s=1)
        self.config.start()
        self.addCleanup(self.config.stop)

    def call_with_response(self, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode('utf-8')
        with patch.object(C.urllib.request, 'urlopen', return_value=io.BytesIO(raw)) as transport:
            result = C.chat([{'role': 'user', 'content': 'Synthetic transport check.'}],
                            transport_attempts=1)
        self.assertEqual(transport.call_count, 1)
        return result

    def call_with_error(self, error, attempts=1):
        with patch.object(C.urllib.request, 'urlopen', side_effect=error) as transport, \
             patch.object(C.time, 'sleep'):
            result = C.chat([{'role': 'user', 'content': 'Synthetic transport check.'}],
                            transport_attempts=attempts)
        return result, transport.call_count

    def assert_failure(self, result, kind, attempts=1):
        text, meta = result
        self.assertIsNone(text)
        self.assertEqual(meta['mode'], 'llm')
        self.assertEqual(meta['error_kind'], kind)
        self.assertEqual(meta['transport_attempts'], attempts)
        self.assertIsInstance(meta['error'], str)
        self.assertTrue(meta['error'])
        self.assertIsInstance(meta['latency_ms'], int)
        self.assertGreaterEqual(meta['latency_ms'], 0)
        serialized = json.dumps(meta)
        for private_text in (self.KEY, self.PRIVATE_URL, self.PRIVATE_BODY,
                             'synthetic-query-token'):
            self.assertNotIn(private_text, serialized)
        return meta

    def test_http_errors_are_one_attempt_and_never_read_provider_body(self):
        for status in (401, 429, 503):
            with self.subTest(status=status):
                error = urllib.error.HTTPError(self.PRIVATE_URL, status,
                                               self.PRIVATE_BODY, {}, None)
                error.read = Mock(return_value=(self.PRIVATE_BODY + self.KEY).encode())
                result, count = self.call_with_error(error)
                meta = self.assert_failure(result, 'http_error')
                self.assertEqual(meta['http_status'], status)
                self.assertEqual(count, 1)
                error.read.assert_not_called()

    def test_timeout_is_distinct_from_connection_error(self):
        for error in (TimeoutError(self.PRIVATE_BODY + self.KEY),
                      urllib.error.URLError(socket.timeout(self.PRIVATE_URL))):
            with self.subTest(error_type=type(error).__name__):
                result, count = self.call_with_error(error)
                self.assert_failure(result, 'timeout')
                self.assertEqual(count, 1)

    def test_connection_error_does_not_echo_url_key_or_private_reason(self):
        errors = [
            urllib.error.URLError(self.PRIVATE_URL + self.KEY + self.PRIVATE_BODY),
            ConnectionResetError(self.PRIVATE_BODY + self.KEY),
        ]
        safe_errors = []
        for error in errors:
            with self.subTest(error_type=type(error).__name__):
                result, count = self.call_with_error(error)
                meta = self.assert_failure(result, 'connection')
                self.assertEqual(count, 1)
                safe_errors.append(meta['error'])
        self.assertEqual(safe_errors[0], safe_errors[1])

    def test_legacy_transport_attempt_count_is_actual_not_requested(self):
        result, count = self.call_with_error(urllib.error.URLError('Synthetic failure.'), attempts=2)
        self.assert_failure(result, 'connection', attempts=2)
        self.assertEqual(count, 2)
        error = urllib.error.HTTPError(self.PRIVATE_URL, 401, self.PRIVATE_BODY, {}, None)
        error.read = Mock(return_value=self.PRIVATE_BODY.encode())
        result, count = self.call_with_error(error, attempts=3)
        self.assert_failure(result, 'http_error', attempts=1)
        self.assertEqual(count, 1)
        error.read.assert_not_called()

    def test_invalid_json_or_response_shape_is_not_a_network_error(self):
        variants = [
            b'not-json', b'\xff', [], {}, {'choices': None}, {'choices': []},
            {'choices': 'wrong type'}, {'choices': [None]},
            {'choices': [{}]}, {'choices': [{'message': None}]},
            {'choices': [{'message': []}]}, {'choices': [{'message': {}}]},
        ]
        for index, value in enumerate(variants):
            with self.subTest(variant=index):
                self.assert_failure(self.call_with_response(value), 'invalid_response')

    def test_empty_content_preserves_valid_finish_reason_and_usage(self):
        usage = {'prompt_tokens': 42, 'completion_tokens': 0, 'total_tokens': 42}
        for content in ('', ' \t\r\n ', None):
            with self.subTest(content_type=type(content).__name__):
                result = self.call_with_response({'model': 'synthetic-test-model', 'usage': usage,
                    'choices': [{'message': {'content': content}, 'finish_reason': 'length'}]})
                meta = self.assert_failure(result, 'empty_response')
                self.assertEqual(meta['finish_reason'], 'length')
                self.assertEqual(meta['usage'], usage)

    def test_non_string_content_is_rejected_without_draft_substitution(self):
        for content in (7, False, {'text': 'Synthetic text.'},
                        [{'type': 'text', 'text': 'Synthetic text.'}]):
            with self.subTest(content_type=type(content).__name__):
                result = self.call_with_response({'choices': [
                    {'message': {'content': content}, 'finish_reason': 'stop'}]})
                self.assert_failure(result, 'invalid_response')

    def test_untrusted_usage_and_finish_reason_cannot_echo_provider_text(self):
        marker = self.PRIVATE_BODY + self.PRIVATE_URL + self.KEY
        for finish_reason in (marker, {'provider_text': marker}):
            with self.subTest(finish_reason_type=type(finish_reason).__name__):
                result = self.call_with_response({'usage': {
                    'prompt_tokens': 12, 'completion_tokens': -1, 'total_tokens': True,
                    'error_body': marker}, 'choices': [
                        {'message': {'content': None}, 'finish_reason': finish_reason}]})
                meta = self.assert_failure(result, 'empty_response')
                self.assertEqual(meta.get('usage'), {'prompt_tokens': 12})
                self.assertIsNone(meta.get('finish_reason'))
        result = self.call_with_response({'usage': marker, 'choices': [
            {'message': {'content': None}, 'finish_reason': 'stop'}]})
        meta = self.assert_failure(result, 'empty_response')
        self.assertFalse(meta.get('usage'))
        self.assertEqual(meta['finish_reason'], 'stop')

    def test_reasoning_content_is_not_used_as_customer_draft(self):
        result = self.call_with_response({'choices': [{'message': {
            'content': None, 'reasoning_content': 'Synthetic internal reasoning.'},
            'finish_reason': 'length'}]})
        self.assert_failure(result, 'empty_response')

    def test_unexpected_client_error_has_fixed_safe_text(self):
        safe_errors = []
        for reason in (self.PRIVATE_BODY + self.KEY, self.PRIVATE_URL):
            result, count = self.call_with_error(RuntimeError(reason))
            safe_errors.append(self.assert_failure(result, 'client_error')['error'])
            self.assertEqual(count, 1)
        self.assertEqual(safe_errors[0], safe_errors[1])

    def test_success_preserves_exact_raw_text_and_metadata(self):
        original = ' \nHi,\nWe will check the design before confirming feasibility.\n '
        usage = {'prompt_tokens': 42, 'completion_tokens': 15, 'total_tokens': 57}
        text, meta = self.call_with_response({'model': 'synthetic-test-model', 'usage': usage,
            'choices': [{'message': {'content': original}, 'finish_reason': 'stop'}]})
        self.assertEqual(text, original)
        self.assertNotIn('error', meta)
        self.assertNotIn('error_kind', meta)
        self.assertEqual(meta['transport_attempts'], 1)
        self.assertEqual(meta['model'], 'synthetic-test-model')
        self.assertEqual(meta['usage'], usage)
        self.assertEqual(meta['finish_reason'], 'stop')


if __name__ == '__main__':
    unittest.main(verbosity=2)
