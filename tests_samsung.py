import io
import sys
import types
import unittest
import zipfile
from xml.sax.saxutils import escape
from predash.samsung import parse_report, domestic_snapshot, combine_with_kis, SamsungError


def workbook(rows):
    """Synthetic anonymous report fixture, not a customer workbook."""
    content = []
    for index, row in enumerate(rows, 1):
        cells = ''.join(f'<c r="{column}{index}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                        for column, value in row.items())
        content.append(f'<row r="{index}">{cells}</row>')
    xml = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<sheetData>'+''.join(content)+'</sheetData></worksheet>')
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('xl/worksheets/sheet1.xml', xml)
    return payload.getvalue()


HEADERS = {'B': '계좌번호', 'K': '고객명', 'O': ' 종목명 ', 'Y': '잔고수량',
           'AA': '현재가', 'AG': '매수금액', 'AJ': '평가금액', 'AN': '평가손익'}


def rows():
    return [
        {'W': '테스트 님 종합 잔고 현황'}, {'G': '기준일자 :', 'I': '2026/10/16'},
        {'E': '계좌번호', 'P': '고객명', 'AE': '매수금액', 'AM': '평가금액'},
        {'E': '0000****-01', 'P': '테스트', 'AE': '100', 'AM': '120'},
        HEADERS,
        {'B': '0000****-01', 'H': 'ISA', 'K': '테스트', 'O': '테스트주식',
         'Y': '2', 'AA': '60', 'AG': '100', 'AJ': '120', 'AN': '20'},
        {'AF': '5/8'}, HEADERS,
        {'O': '현금잔고(예수금)', 'Y': '0', 'AA': '0', 'AG': '0', 'AJ': '50', 'AN': '0'},
        {'B': '0000****-02', 'H': '연금', 'K': '테스트', 'O': '테스트주식',
         'Y': '3', 'AA': '60', 'AG': '150', 'AJ': '180', 'AN': '30'},
        {'B': '전체 합계', 'AG': '250', 'AJ': '350', 'AN': '50'}]


class ReportTests(unittest.TestCase):
    def test_headers_summary_and_page_breaks_do_not_duplicate_holdings(self):
        report = parse_report(workbook(rows()))
        self.assertEqual(len(report['positions']), 3)
        self.assertEqual(report['positions'][1]['account'], '0000****-01')
        self.assertEqual(report['positions'][2]['account_type'], '연금')
        self.assertEqual(report['totals']['value'], 350)
        self.assertEqual(report['totals']['pnl'], 50)  # Cash is not profit.

    def test_source_total_mismatch_is_rejected(self):
        source = rows()
        source[-1] = dict(source[-1], AJ='999')
        with self.assertRaisesRegex(SamsungError, '합계가 맞지'):
            parse_report(workbook(source))

    def test_missing_metadata_or_detail_is_rejected(self):
        for source in (rows()[1:], rows()[:5], rows()[:-1]):
            with self.assertRaises(SamsungError):
                parse_report(workbook(source))

    def test_zero_and_nonfinite_are_not_confused(self):
        source = rows()
        source[5] = dict(source[5], Y='NaN')
        with self.assertRaises(SamsungError):
            parse_report(workbook(source))

    def test_same_payload_has_same_identity(self):
        payload = workbook(rows())
        self.assertEqual(parse_report(payload)['id'], parse_report(payload)['id'])

    def test_unconfirmed_codes_and_other_assets_are_not_in_domestic_view(self):
        report = parse_report(workbook(rows()))
        links = {r['id']: {'kind': '주식', 'code': '123456', 'verified': False}
                 for r in report['positions']}
        self.assertEqual(domestic_snapshot(report, links)['positions'], [])

    def test_confirmed_positions_aggregate_by_code_across_accounts(self):
        report = parse_report(workbook(rows()))
        links = {r['id']: {'kind': '주식', 'code': '123456', 'verified': True}
                 for r in report['positions'] if r['quantity'] > 0}
        snapshot = domestic_snapshot(report, links)
        self.assertEqual(len(snapshot['positions']), 1)
        position = snapshot['positions'][0]
        self.assertEqual((position['quantity'], position['value'], position['average_cost']), (5, 300, 50))
        kis = {'mode': 'real', 'fetched': '2026-10-16', 'positions': [
            dict(code='123456', name='테스트주식', quantity=1, average_cost=40, value=60, pnl=20)]}
        combined = combine_with_kis(snapshot, kis)
        self.assertEqual(combined['value'], 360)
        self.assertEqual(combined['positions'][0]['quantity'], 6)
        self.assertAlmostEqual(combined['positions'][0]['average_cost'], 290/6)
        self.assertEqual(combined['pnl'], 70)
        kis['mode'] = 'demo'
        with self.assertRaisesRegex(SamsungError, '모의 계좌'):
            combine_with_kis(snapshot, kis)

    def test_bad_xlsx_is_a_user_facing_error(self):
        with self.assertRaises(SamsungError):
            parse_report(b'not an xlsx')


if __name__ == '__main__':
    unittest.main()
