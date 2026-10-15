from copy import deepcopy
import unittest
from predash.portfolio import account_view, evidence_for_account
from predash.samsung import SamsungError


def state():
    report = {'owner': '명의자A', 'asof': '2026-10-16', 'positions': [
        {'id': '1', 'account': '0000****-01', 'name': '주식A', 'quantity': 2,
         'cost': 100, 'value': 120, 'pnl': 20},
        {'id': '2', 'account': '0000****-01', 'name': 'ETF A', 'quantity': 3,
         'cost': 150, 'value': 180, 'pnl': 30}]}
    return {'snapshot': {'mode': 'real', 'fetched': '2026-10-17', 'value': 90, 'pnl': 10,
        'positions': [{'code': '123456', 'name': '주식A', 'quantity': 1,
                       'average_cost': 80, 'price': 90, 'value': 90, 'pnl': 10, 'weight': 100}]},
        'samsung_files': {'file': report},
        'samsung_links_file': {'1': {'kind': '주식', 'code': '123456'},
                               '2': {'kind': 'ETF', 'code': '234567'}},
        'samsung_verified_file': {'1': '주식:123456', '2': 'ETF:234567'}}


class AccountViewTests(unittest.TestCase):
    def test_combined_view_leaves_original_kis_snapshot_untouched(self):
        source = state()
        original = deepcopy(source)
        view = account_view(source, ['file'])
        self.assertEqual(source, original)
        self.assertEqual(len(view['positions']), 2)
        self.assertEqual((view['value'], view['pnl']), (390, 60))
        share = next(p for p in view['positions'] if p['code'] == '123456')
        self.assertEqual(share['quantity'], 3)
        self.assertEqual(share['average_cost'], 60)
        self.assertEqual(share['price'], 70)
        self.assertAlmostEqual(sum(p['weight'] for p in view['positions']), 100)
        self.assertIn('2026-10-16', share['source'])
        self.assertIn('2026-10-17', share['source'])

    def test_kis_refresh_replaces_only_the_kis_component(self):
        source = state()
        before = account_view(source, ['file'])
        source['snapshot']['positions'][0].update(value=100, pnl=20, price=100)
        after = account_view(source, ['file'])
        self.assertEqual(after['value']-before['value'], 10)
        self.assertEqual(after['positions'][0]['quantity'], 3)
        self.assertEqual(len(source['samsung_files']), 1)

    def test_samsung_only_and_kis_only(self):
        source = state()
        self.assertEqual(account_view(source, [])['value'], 90)
        source.pop('snapshot')
        self.assertEqual(account_view(source, ['file'])['value'], 300)
        self.assertNotIn('KIS', account_view(source, ['file'])['source_label'])
        self.assertIsNone(account_view(source, []))

    def test_changed_code_requires_reverification(self):
        source = state()
        source['samsung_links_file']['1']['code'] = '999999'
        view = account_view(source, ['file'])
        self.assertNotIn('999999', [p['code'] for p in view['positions']])

    def test_same_file_and_same_account_are_not_added_twice(self):
        source = state()
        self.assertEqual(account_view(source, ['file', 'file'])['value'], 390)
        source['samsung_files']['other'] = deepcopy(source['samsung_files']['file'])
        with self.assertRaisesRegex(SamsungError, '같은 명의자'):
            account_view(source, ['file', 'other'])

    def test_other_owner_is_included_only_if_selected(self):
        source = state()
        source['samsung_files']['other'] = deepcopy(source['samsung_files']['file'])
        source['samsung_files']['other']['owner'] = '명의자B'
        source['samsung_links_other'] = deepcopy(source['samsung_links_file'])
        source['samsung_verified_other'] = deepcopy(source['samsung_verified_file'])
        self.assertEqual(account_view(source, ['file'])['value'], 390)
        self.assertEqual(account_view(source, ['file', 'other'])['value'], 690)

    def test_demo_cannot_merge_real_files(self):
        source = state()
        source['snapshot']['mode'] = 'demo'
        with self.assertRaisesRegex(SamsungError, '모의 잔고'):
            account_view(source, ['file'])

    def test_financial_evidence_is_filtered_and_current_refresh_wins(self):
        source = state()
        source['samsung_dart_file'] = {'123456': {'metrics': 'older'}, '234567': {'metrics': 'ETF'}}
        source['reports'] = {'123456': {'metrics': 'newer'}, '999999': {'metrics': 'other'}}
        source['samsung_dart_errors_file'] = {'123456': 'old failure'}
        reports, errors = evidence_for_account(source, ['file'], account_view(source, ['file']))
        self.assertEqual(reports, {'123456': {'metrics': 'newer'}})
        self.assertEqual(errors, {})


if __name__ == '__main__':
    unittest.main()
