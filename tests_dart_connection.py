import sys
import types
import unittest
from unittest.mock import Mock, patch

try:
    import requests
except ImportError:
    sys.modules['requests'] = types.SimpleNamespace(RequestException=Exception)

import predash.official as official
from predash.official import Official, DataError


class RequestFailure(Exception):
    pass


class RequestTimeout(RequestFailure):
    pass


def response(status='000', http=200):
    return types.SimpleNamespace(status_code=http, json=lambda: {
        'status': status, 'corp_code': '00126380', 'stock_code': '005930', 'corp_name': '삼성전자'})


class DARTConnectionTests(unittest.TestCase):
    def requests(self, reply=None, error=None):
        return types.SimpleNamespace(get=Mock(return_value=reply, side_effect=error),
                                     Timeout=RequestTimeout, RequestException=RequestFailure)

    def test_success_is_checked_once_and_reuses_samsung_identity(self):
        transport = self.requests(response())
        provider = Official(dart_key='test-key')
        with patch.object(official, 'requests', transport):
            provider.check_dart_connection()
            provider.check_dart_connection()
            self.assertEqual(provider.corp('005930'), '00126380')
        self.assertEqual(transport.get.call_count, 1)
        self.assertEqual(transport.get.call_args.kwargs['timeout'], (5, 8))

    def test_timeout_stops_every_holding_in_the_refresh_without_retrying_the_probe(self):
        transport = self.requests(error=RequestTimeout())
        provider = Official(dart_key='test-key')
        provider.corp = Mock()
        with patch.object(official, 'requests', transport):
            for code in ('005930', '000660', '006400'):
                with self.assertRaisesRegex(DataError, '소량 API 접속 진단'):
                    provider.holding_report(code)
        self.assertEqual(transport.get.call_count, 1)
        provider.corp.assert_not_called()

    def test_authentication_and_http_errors_are_distinct_from_timeouts(self):
        for reply, expected in ((response('010'), '등록되지 않은 DART 키'),
                                (response(http=403), 'HTTP 403')):
            provider = Official(dart_key='test-key')
            with patch.object(official, 'requests', self.requests(reply)):
                with self.assertRaisesRegex(DataError, expected):
                    provider.check_dart_connection()
            self.assertTrue(provider.dart_probe_error)

    def test_all_registered_codes_bypass_public_search_but_require_api_identity(self):
        for code, identity in official._REGISTERED_COMPANIES.items():
            with self.subTest(code=code):
                provider = Official(dart_key='test-key')
                provider.dart = Mock(return_value={'corp_code': identity['corp_code'],
                    'stock_code': identity['issuer_stock_code'], 'corp_name': '검증용 기업'})
                with patch.object(official, 'get', side_effect=AssertionError('검색 페이지 호출 금지')):
                    self.assertEqual(provider.corp(code), identity['corp_code'])
                provider.dart.assert_called_once_with('company.json', corp_code=identity['corp_code'])


if __name__ == '__main__':
    unittest.main()
