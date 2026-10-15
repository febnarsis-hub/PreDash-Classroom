"""Build the account view without replacing the broker's original balance."""
from copy import deepcopy
from predash.samsung import domestic_snapshot, SamsungError


def account_view(state, selected_files):
    kis = state.get('snapshot')
    if not selected_files:
        return deepcopy(kis) if kis is not None else None
    if kis and kis.get('mode') != 'real':
        raise SamsungError('삼성증권 실제 잔고와 KIS 모의 잔고는 합산하지 않습니다. 삼성 파일 선택을 해제하세요.')
    components = []
    if kis:
        components.append((kis, 'KIS', str(kis['fetched'])))
    seen_accounts = set()
    for identity in dict.fromkeys(selected_files):
        report = state.get('samsung_files', {}).get(identity)
        if report is None:
            raise SamsungError('선택한 삼성증권 파일을 09 메뉴에서 다시 업로드하세요.')
        accounts = {(report['owner'], r['account']) for r in report['positions']}
        if accounts & seen_accounts:
            raise SamsungError('같은 명의자·계좌가 여러 파일에 포함되어 있습니다. 해당 계좌의 최신 파일 하나만 선택하세요.')
        seen_accounts.update(accounts)
        verified = state.get('samsung_verified_'+identity, {})
        links = deepcopy(state.get('samsung_links_'+identity, {}))
        for row_id, link in links.items():
            link['verified'] = verified.get(row_id) == link.get('kind', '')+':'+link.get('code', '')
        snapshot = domestic_snapshot(report, links)
        if not snapshot['positions']:
            raise SamsungError('선택한 파일에 확인된 국내 주식·ETF가 없습니다. 09에서 종목코드를 확인하세요.')
        components.append((snapshot, '삼성증권 파일 · '+report['owner'], report['asof']))
    grouped = {}
    sources = []
    for snapshot, source, asof in components:
        sources.append(source+' '+asof)
        for row in snapshot['positions']:
            code = row['code']
            item = grouped.setdefault(code, dict(code=code, name=row['name'], quantity=0.,
                cost=0., value=0., pnl=0., asset_kind='미확인', source_parts=[]))
            kind = row.get('asset_kind', '미확인')
            if kind != '미확인':
                if item['asset_kind'] not in ('미확인', kind):
                    raise SamsungError('같은 코드의 주식·ETF 구분이 서로 다릅니다.')
                item['asset_kind'] = kind
            item['quantity'] += row['quantity']
            item['cost'] += row['cost'] if 'cost' in row else row['average_cost']*row['quantity']
            item['value'] += row['value']
            item['pnl'] += row['pnl']
            item['source_parts'].append(source+' '+asof)
    positions = list(grouped.values())
    value = sum(p['value'] for p in positions)
    for position in positions:
        quantity = position['quantity']
        if quantity <= 0:
            raise SamsungError('양수 수량의 보유종목만 통합할 수 있습니다.')
        position.update(average_cost=position['cost']/quantity, price=position['value']/quantity,
            weight=position['value']/value*100 if value else 0,
            source=' / '.join(position.pop('source_parts')))
    return dict(positions=positions, value=value, pnl=sum(p['pnl'] for p in positions),
                mode='real', fetched=' / '.join(sources), integrated=True,
                source_label='KIS + 선택한 삼성증권 파일 기준' if kis else '선택한 삼성증권 파일 기준')


def evidence_for_account(state, selected_files, snapshot):
    reports, errors = {}, {}
    for identity in selected_files:
        reports.update(state.get('samsung_dart_'+identity, {}))
        errors.update(state.get('samsung_dart_errors_'+identity, {}))
    reports.update(state.get('reports', {}))
    errors.update(state.get('report_errors', {}))
    eligible = {p['code'] for p in snapshot['positions'] if p.get('asset_kind') != 'ETF'}
    return ({code: r for code, r in reports.items() if code in eligible},
            {code: e for code, e in errors.items() if code in eligible and code not in reports})
