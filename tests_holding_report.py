import sys
import types
import unittest
from datetime import date
from unittest.mock import Mock, patch

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


class CorporateResolutionTests(unittest.TestCase):
    def test_held_companies_resolve_without_directory_download_and_are_cached(self):
        for code, corp, name in [('012450', '00126566', '한화에어로스페이스'),
                                 ('058470', '00369657', '리노공업')]:
            with self.subTest(code=code):
                provider = Official(dart_key='test-key')
                provider.dart = Mock(return_value={'corp_code': corp, 'stock_code': code,
                                                  'corp_name': name})
                with patch('predash.official.get', side_effect=AssertionError('전체 목록 다운로드 금지')):
                    self.assertEqual(provider.corp(code), corp)
                    self.assertEqual(provider.corp(code), corp)
                provider.dart.assert_called_once_with('company.json', corp_code=corp)
                self.assertEqual(provider.names[code], name)
                self.assertIsNone(provider.corps)

    def test_mismatched_or_missing_identity_never_uses_the_hint(self):
        for company in [{'corp_code': '00126566', 'stock_code': '005930'},
                        {'corp_code': '99999999', 'stock_code': '012450'}, {}]:
            provider = Official(dart_key='test-key')
            provider.dart = Mock(return_value=company)
            with self.assertRaisesRegex(DataError, '일치하지 않아'):
                provider.corp('012450')
            self.assertEqual(provider.resolved_corps, {})

    def test_authentication_failure_is_not_bypassed(self):
        provider = Official(dart_key='test-key')
        provider.dart = Mock(side_effect=DataError('등록되지 않은 DART 키'))
        with self.assertRaisesRegex(DataError, '등록되지 않은 DART 키'):
            provider.corp('058470')
        self.assertEqual(provider.resolved_corps, {})

    def test_full_directory_remains_authoritative(self):
        provider = Official(dart_key='test-key')
        provider.corps = {'012450': '12345678', '005930': '00126380'}
        provider.dart = Mock(side_effect=AssertionError('추가 조회 불필요'))
        self.assertEqual(provider.corp('012450'), '12345678')
        self.assertEqual(provider.corp('005930'), '00126380')


if __name__ == '__main__':
    unittest.main()
