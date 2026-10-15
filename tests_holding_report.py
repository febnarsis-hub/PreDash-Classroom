import sys
import types
import unittest
from datetime import date
from unittest.mock import Mock

try:
    import requests
except ImportError:
    sys.modules['requests'] = types.SimpleNamespace(RequestException=Exception)

from predash.official import Official, DataError


class HoldingReportTests(unittest.TestCase):
    def provider(self):
        provider = Official(dart_key='test-key', price_key='')
        provider.corp = Mock(return_value='00126380')
        provider.names = {'005930': '삼성전자'}
        provider.latest_period_metrics = Mock(return_value={'profit': 30, 'prior_profit': 20})
        provider.dart = Mock(return_value={'list': [
            {'rcept_dt': '20261013', 'report_nm': '공급계약', 'rcept_no': '20261013000001'}]})
        provider.annual = Mock(side_effect=DataError('결산 자료 조회 실패'))
        provider.price = Mock(side_effect=AssertionError('시세 조회는 필요하지 않습니다.'))
        return provider

    def test_missing_annual_and_price_key_do_not_discard_metrics_or_notices(self):
        provider = self.provider()
        result = provider.holding_report('005930', date(2026, 10, 16))
        self.assertEqual(result['metrics']['profit'], 30)
        self.assertEqual(result['disclosures'][0]['title'], '공급계약')
        self.assertEqual(result['errors'], {'annual': '결산 자료 조회 실패'})
        self.assertEqual(result['years'], [])
        provider.price.assert_not_called()

    def test_metrics_failure_preserves_notices_and_reason(self):
        provider = self.provider()
        provider.latest_period_metrics.side_effect = DataError('실적 호출 한도 초과')
        result = provider.holding_report('005930', date(2026, 10, 16))
        self.assertIsNone(result['metrics'])
        self.assertEqual(result['errors']['metrics'], '실적 호출 한도 초과')
        self.assertEqual(len(result['disclosures']), 1)

    def test_notice_failure_is_distinct_from_success_with_no_notices(self):
        provider = self.provider()
        provider.dart.side_effect = DataError('공시 접속 실패')
        result = provider.holding_report('005930', date(2026, 10, 16))
        self.assertEqual(result['metrics']['profit'], 30)
        self.assertEqual(result['errors']['disclosures'], '공시 접속 실패')
        provider.dart.side_effect = None
        provider.dart.return_value = None
        result = provider.holding_report('005930', date(2026, 10, 16))
        self.assertEqual(result['disclosures'], [])
        self.assertNotIn('disclosures', result['errors'])

    def test_missing_key_does_not_call_dart(self):
        provider = self.provider()
        provider.dart_key = ''
        with self.assertRaisesRegex(DataError, 'DART 인증키가 없습니다'):
            provider.holding_report('005930')
        provider.corp.assert_not_called()

    def test_annual_series_keeps_a_single_basis(self):
        provider = self.provider()
        def annual(corp, year, basis):
            if basis == 'CFS' and year != 2025:
                return None
            return {'year': year, 'profit': 10, 'revenue': 100}
        provider.annual.side_effect = annual
        result = provider.holding_report('005930', date(2026, 10, 16))
        self.assertEqual(result['basis'], 'OFS')
        self.assertEqual([row['year'] for row in result['years']], [2023, 2024, 2025])


if __name__ == '__main__':
    unittest.main()
