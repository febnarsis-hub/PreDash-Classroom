import sys
import types
import unittest
from unittest.mock import Mock, patch

try:
    import requests
except ImportError:
    sys.modules['requests'] = types.SimpleNamespace(RequestException=Exception)

from predash.official import Official, DataError


def search_page(*codes):
    return types.SimpleNamespace(text=''.join(
        f'<a onclick="openCorpInfoNew(\'{code}\', \'winCorpInfo\', \'/dsae001/selectPopup.ax\');">회사</a>'
        for code in codes))


class ListedCompanyResolutionTests(unittest.TestCase):
    def test_new_stock_resolves_via_small_public_search_then_authenticated_identity(self):
        provider = Official(dart_key='test-key')
        provider.dart = Mock(return_value={'corp_code': '00126380', 'stock_code': '123456', 'corp_name': '삼성전자'})
        with patch('predash.official.get', return_value=search_page('00126380', '00126380')) as get:
            self.assertEqual(provider.corp('123456'), '00126380')
            self.assertEqual(provider.corp('123456'), '00126380')
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], 'https://dart.fss.or.kr/dsab001/search.ax')
        self.assertEqual(get.call_args.args[1]['textCrpNm'], '123456')
        self.assertNotIn('crtfc_key', get.call_args.args[1])
        provider.dart.assert_called_once_with('company.json', corp_code='00126380')
        self.assertIsNone(provider.corps)

    def test_no_match_and_ambiguous_match_never_trigger_bulk_download(self):
        for page in (search_page(), search_page('00126380', '00164779')):
            provider = Official(dart_key='test-key')
            provider.dart = Mock()
            with patch('predash.official.get', return_value=page) as get:
                with self.assertRaisesRegex(DataError, '하나로 확인하지 못했습니다'):
                    provider.corp('123456')
            self.assertEqual(get.call_count, 1)
            provider.dart.assert_not_called()

    def test_public_lookup_does_not_bypass_api_authentication_or_identity_checks(self):
        for reply in ({'corp_code': '00126380', 'stock_code': '000660'},
                      {'corp_code': '99999999', 'stock_code': '123456'}):
            provider = Official(dart_key='test-key')
            provider.dart = Mock(return_value=reply)
            with patch('predash.official.get', return_value=search_page('00126380')):
                with self.assertRaisesRegex(DataError, '일치하지 않아'):
                    provider.corp('123456')
            self.assertEqual(provider.resolved_corps, {})
        provider.dart.side_effect = DataError('등록되지 않은 DART 키')
        with patch('predash.official.get', return_value=search_page('00126380')):
            with self.assertRaisesRegex(DataError, '등록되지 않은 DART 키'):
                provider.corp('123456')

    def test_preferred_share_uses_verified_issuer_without_renaming_the_security(self):
        provider = Official(dart_key='test-key')
        provider.names['005387'] = '현대차3우B'
        provider.dart = Mock(return_value={'corp_code': '00164742', 'stock_code': '005380', 'corp_name': '현대자동차'})
        with patch('predash.official.get', return_value=search_page('00164742')):
            self.assertEqual(provider.corp('005387'), '00164742')
        self.assertEqual(provider.names['005387'], '현대차3우B')

    def test_unverified_share_class_mismatch_is_rejected(self):
        provider = Official(dart_key='test-key')
        provider.dart = Mock(return_value={'corp_code': '00126380', 'stock_code': '123456'})
        with patch('predash.official.get', return_value=search_page('00126380')):
            with self.assertRaisesRegex(DataError, '일치하지 않아'):
                provider.corp('005935')


if __name__ == '__main__':
    unittest.main()
