from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.request import Request
from rest_framework.throttling import AnonRateThrottle

from smmsapp.services.audit import get_client_ip


class ProxyClientIPTests(SimpleTestCase):
    def test_forwarded_headers_are_ignored_without_a_trusted_proxy(self):
        request = RequestFactory().get(
            '/', REMOTE_ADDR='10.0.0.8', HTTP_X_FORWARDED_FOR='198.51.100.4',
        )
        with override_settings(REST_FRAMEWORK={'NUM_PROXIES': 0}):
            self.assertEqual(get_client_ip(request), '10.0.0.8')
            self.assertEqual(AnonRateThrottle().get_ident(Request(request)), '10.0.0.8')

    def test_single_edge_client_address_matches_drf_throttle_identity(self):
        request = RequestFactory().get(
            '/', REMOTE_ADDR='10.0.0.8', HTTP_X_FORWARDED_FOR='198.51.100.4',
        )
        with override_settings(REST_FRAMEWORK={'NUM_PROXIES': 1}):
            self.assertEqual(get_client_ip(request), '198.51.100.4')
            self.assertEqual(AnonRateThrottle().get_ident(Request(request)), '198.51.100.4')

    def test_proxy_chain_uses_the_configured_trusted_hop_count(self):
        request = RequestFactory().get(
            '/', REMOTE_ADDR='10.0.0.8',
            HTTP_X_FORWARDED_FOR='198.51.100.4, 203.0.113.5',
        )
        with override_settings(REST_FRAMEWORK={'NUM_PROXIES': 2}):
            self.assertEqual(get_client_ip(request), '198.51.100.4')
            self.assertEqual(AnonRateThrottle().get_ident(Request(request)), '198.51.100.4')
