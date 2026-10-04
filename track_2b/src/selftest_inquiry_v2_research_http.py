"""P4 through actual HTTP and P3 authorization/persistence boundaries."""
import unittest
from unittest.mock import patch
import selftest_inquiry_v2_context_http as http_tests
from selftest_inquiry_v2_research import Provider, moq_page


class ResearchHTTPTests(unittest.TestCase):
    setUpClass = classmethod(http_tests.PrivateContextHTTPTests.setUpClass.__func__)
    tearDownClass = classmethod(http_tests.PrivateContextHTTPTests.tearDownClass.__func__)
    setUp = http_tests.PrivateContextHTTPTests.setUp
    request = http_tests.PrivateContextHTTPTests.request

    def payload(self):
        return {"inquiry": {"primary": {"text": "What is your MOQ for 400 work vests?"}}, "research": {"enabled": True}}

    def test_research_confirm_then_reuse_actual_http(self):
        provider = Provider([moq_page(200), moq_page(300, "supplier-b.com")])
        with patch('inquiry_v2.research_executor.configured_provider', return_value=provider):
            status, first, _ = self.request('/v2/inquiry', self.payload())
            self.assertEqual(status, 200)
            candidate = first['trust']['research']['results'][0]['working_candidate_id']
            self.assertIsNone(first['reply']['draft'])
            status, view, _ = self.request('/v2/company-context')
            self.assertFalse(any(c['status'] == 'company_confirmed' for c in view['candidates']))
            status, _, _ = self.request('/v2/company-context/confirm', {
                'candidate_id': candidate, 'scope_spec': {'product_categories': ['work vest']}})
            self.assertEqual(status, 200)
            status, second, _ = self.request('/v2/inquiry', self.payload())
            self.assertEqual(status, 200)
            self.assertEqual(len(provider.queries), 1)
            self.assertEqual(second['trust']['research']['execution_status'], 'skipped')
            self.assertTrue(any(c['status'] == 'company_confirmed' for c in second['values']))

    def test_offline_optional_core_and_anonymous_no_persistence(self):
        with patch('inquiry_v2.research_executor.configured_provider', return_value=Provider(offline=True)):
            status, result, _ = self.request('/v2/inquiry', self.payload(), authorized=False)
            self.assertEqual(status, 200)
            self.assertEqual(result['advance']['action'], 'INTERNAL_COSTING')
            self.assertTrue(result['trust']['needs_human_approval'])
            self.assertFalse(self.path.exists())

    def test_identity_verification_requires_operator_authorization(self):
        payload = self.payload()
        payload['research']['identity_verification'] = {
            'domain': 'synthetic-buyer.com', 'changes_decision': 'Whether to allocate development budget'}
        with patch('inquiry_v2.research_executor.configured_provider', return_value=Provider()) as factory:
            status, _, _ = self.request('/v2/inquiry', payload, authorized=False)
            self.assertEqual(status, 403)
            factory.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
