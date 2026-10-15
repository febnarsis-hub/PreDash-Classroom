"""Read Samsung OZ report XLSX exports without storing personal holdings in source."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import re
import zipfile
from xml.etree import ElementTree as ET


class SamsungError(ValueError):
    pass


NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REQUIRED = ('종목명', '잔고수량', '현재가', '매수금액', '평가금액', '평가손익')


def compact(value):
    return re.sub(r'\s+', '', str(value))


def amount(value):
    try:
        result = Decimal(str(value).replace(',', '').strip())
        if not result.is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError):
        raise SamsungError('잔고 표에 숫자가 없거나 올바르지 않은 금액이 있습니다.') from None


def _xml(archive, name):
    raw = archive.read(name)
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise SamsungError('지원하지 않는 XML 형식입니다.')
    return ET.fromstring(raw)


def _rows(archive):
    strings = []
    if 'xl/sharedStrings.xml' in archive.namelist():
        strings = [''.join(n.itertext()) for n in _xml(archive, 'xl/sharedStrings.xml').findall('m:si', NS)]
    for path in sorted(archive.namelist()):
        if not re.fullmatch(r'xl/worksheets/sheet\d+\.xml', path):
            continue
        for row in _xml(archive, path).findall('.//m:sheetData/m:row', NS):
            values = {}
            for cell in row.findall('m:c', NS):
                column = re.sub(r'\d+', '', cell.get('r', ''))
                value = cell.findtext('m:v', '', NS)
                if cell.get('t') == 's':
                    value = strings[int(value)]
                elif cell.get('t') == 'inlineStr':
                    node = cell.find('m:is', NS)
                    value = ''.join(node.itertext()) if node is not None else ''
                if value != '':
                    values[column] = value
            if values:
                yield path, row.get('r', ''), values


def parse_report(payload):
    """Read detail rows only; repeated summary tables never become holdings."""
    if len(payload) > 10_000_000:
        raise SamsungError('파일은 10MB 이하로 올려주세요.')
    owner = asof = None
    positions = []
    total = None
    headers = None
    account = account_type = ''
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if sum(i.file_size for i in archive.infolist()) > 40_000_000:
                raise SamsungError('압축 해제 크기가 너무 큽니다.')
            for sheet, row_number, row in _rows(archive):
                for value in row.values():
                    match = re.fullmatch(r'\s*(.+?)\s*님\s*종합\s*잔고\s*현황\s*', str(value))
                    if match:
                        if owner and owner != match[1].strip():
                            raise SamsungError('한 파일에 여러 명의자가 있습니다. 파일을 나눠주세요.')
                        owner = match[1].strip()
                if any(compact(v) == '기준일자:' for v in row.values()):
                    found = next((v for v in row.values() if re.fullmatch(r'\d{4}/\d{2}/\d{2}', str(v))), None)
                    if found:
                        day = datetime.strptime(found, '%Y/%m/%d').date().isoformat()
                        if asof and asof != day:
                            raise SamsungError('서로 다른 기준일의 보고서는 나눠서 올려주세요.')
                        asof = day
                lookup = {compact(v): col for col, v in row.items()}
                if all(name in lookup for name in REQUIRED):
                    headers = lookup
                    continue
                if headers is None:
                    continue
                if any(compact(v) == '전체합계' for v in row.values()):
                    candidate = {key: amount(row.get(headers[label], '')) for key, label in
                                 (('cost', '매수금액'), ('value', '평가금액'), ('pnl', '평가손익'))}
                    if total is not None and candidate != total:
                        raise SamsungError('전체 합계가 여러 개이며 서로 다릅니다.')
                    total = candidate
                    headers = None
                    continue
                name = row.get(headers['종목명'], '').strip()
                if not name:
                    continue
                account_column = headers.get('계좌번호')
                if row.get(account_column):
                    account = row[account_column].strip()
                    # Account description is the unlabelled column between account and customer.
                    customer_column = headers.get('고객명', '')
                    ordered = sorted(row, key=lambda col: (len(col), col))
                    before = ordered.index(customer_column) if customer_column in ordered else 0
                    account_type = next((row[col] for col in reversed(ordered[:before])
                                         if col != account_column), '')
                if not account:
                    raise SamsungError('상세 잔고의 계좌 구분을 확인할 수 없습니다.')
                numeric = {key: amount(row.get(headers[label], '')) for key, label in
                           (('quantity', '잔고수량'), ('raw_price', '현재가'), ('cost', '매수금액'),
                            ('value', '평가금액'), ('pnl', '평가손익'))}
                if any(numeric[k] < 0 for k in ('quantity', 'cost', 'value')):
                    raise SamsungError('음수 수량 또는 금액은 이 가져오기에서 지원하지 않습니다.')
                positions.append({'id': f'{sheet}:{row_number}', 'account': account,
                    'account_type': account_type, 'name': name,
                    **{k: float(v) for k, v in numeric.items()}})
        if not owner or not asof or not positions or total is None:
            raise SamsungError('종합 잔고 현황의 명의자·기준일·상세 잔고·전체 합계가 필요합니다.')
        for key in ('cost', 'value', 'pnl'):
            actual = sum(Decimal(str(row[key])) for row in positions)
            if abs(actual-total[key]) > Decimal('1'):
                raise SamsungError('상세 잔고와 전체 합계가 맞지 않습니다. 모든 페이지를 저장해 주세요.')
        return {'id': hashlib.sha256(payload).hexdigest(), 'owner': owner, 'asof': asof,
                'positions': positions, 'totals': {k: float(v) for k, v in total.items()}}
    except SamsungError:
        raise
    except (zipfile.BadZipFile, KeyError, IndexError, ET.ParseError, ValueError, RuntimeError):
        raise SamsungError('정상적인 삼성증권 종합 잔고 현황 XLSX 파일인지 확인하세요.') from None


def domestic_snapshot(report, links):
    """Only explicitly confirmed domestic stock/ETF codes enter the domestic view."""
    grouped = {}
    for row in report['positions']:
        link = links.get(row['id'], {})
        if link.get('kind') not in ('주식', 'ETF') or not link.get('verified'):
            continue
        code = link.get('code', '')
        if not re.fullmatch(r'[0-9]{6}', code) or row['quantity'] <= 0:
            raise SamsungError('확인된 국내 종목코드와 양수 수량이 필요합니다.')
        if code in grouped and grouped[code]['asset_kind'] != link['kind']:
            raise SamsungError('같은 종목코드의 주식/ETF 구분이 서로 다릅니다.')
        item = grouped.setdefault(code, dict(code=code, name=row['name'], quantity=0., cost=0.,
            value=0., pnl=0., asset_kind=link['kind'], source='삼성증권 파일'))
        for key in ('quantity', 'cost', 'value', 'pnl'):
            item[key] += row[key]
    return _snapshot(list(grouped.values()), report['asof'])


def _snapshot(positions, fetched):
    value = sum(p['value'] for p in positions)
    for p in positions:
        p['price'] = p['value']/p['quantity']
        p['average_cost'] = p['cost']/p['quantity']
        p['weight'] = p['value']/value*100 if value else 0
    return {'positions': positions, 'value': value, 'pnl': sum(p['pnl'] for p in positions),
            'mode': 'real', 'fetched': fetched}


def combine_with_kis(samsung, kis):
    if kis.get('mode') != 'real':
        raise SamsungError('실제 삼성증권 잔고와 KIS 모의 계좌는 합산하지 않습니다.')
    grouped = {}
    for snapshot, source in ((samsung, '삼성증권 파일'), (kis, 'KIS')):
        for row in snapshot.get('positions', []):
            code = row['code']
            item = grouped.setdefault(code, dict(code=code, name=row['name'], quantity=0.,
                cost=0., value=0., pnl=0., asset_kind=row.get('asset_kind', '미확인'), source=''))
            item['quantity'] += row['quantity']
            item['cost'] += row.get('cost', row['average_cost']*row['quantity'])
            item['value'] += row['value']
            item['pnl'] += row['pnl']
            item['source'] = source if not item['source'] else '삼성증권 파일 + KIS'
    return _snapshot(list(grouped.values()), f"삼성 {samsung['fetched']} / KIS {kis['fetched']}")
