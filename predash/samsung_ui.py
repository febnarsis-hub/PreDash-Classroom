"""Session-only Samsung file import and an explicitly selected combined view."""
from datetime import date
import re
import streamlit as st
from predash.samsung import parse_report, domestic_snapshot, combine_with_kis, compact, SamsungError
from predash.official import DataError
from predash.visuals import compact_dashboard


def render(provider_factory, has_price_key, has_dart_key):
    st.title('삼성증권 · 통합 잔고')
    st.caption('삼성증권 종합 잔고 현황 XLSX를 그대로 올리세요. 파일 기준 금액이며 실시간 계좌 연동은 아닙니다.')
    uploads = st.file_uploader('삼성증권 잔고 파일', type=['xlsx'], accept_multiple_files=True)
    reports = st.session_state.setdefault('samsung_files', {})
    for uploaded in uploads or []:
        try:
            report = parse_report(uploaded.getvalue())
            if report['id'] not in reports:
                reports[report['id']] = {**report, 'filename': uploaded.name}
        except SamsungError as exc:
            st.error(f'{uploaded.name} · {exc}')
    if not reports:
        st.info('종합 잔고 현황의 모든 페이지를 엑셀로 저장한 파일이 필요합니다.')
        return
    selected = st.selectbox('가져올 명의자·파일', list(reports),
        format_func=lambda key: f"{reports[key]['owner']} · {reports[key]['filename']} · {reports[key]['asof']}")
    report = reports[selected]
    st.caption('파일별·명의자별로 구분합니다. 다른 파일의 자산을 자동으로 합산하지 않습니다.')
    a, b, c = st.columns(3)
    a.metric('원본 총평가액', f"{report['totals']['value']:,.0f}원")
    b.metric('원본 평가손익', f"{report['totals']['pnl']:+,.0f}원")
    c.metric('상세 잔고 행', str(len(report['positions'])))
    st.caption(f"기준일 {report['asof']} · 상세 금액과 전체 합계 일치 확인 · 현금·펀드·채권·해외자산 포함")
    links_key = 'samsung_links_'+selected
    verified_key = 'samsung_verified_'+selected
    version_key = 'samsung_editor_version_'+selected
    saved = st.session_state.get(links_key, {})
    verified = st.session_state.get(verified_key, {})
    data = []
    for row in report['positions']:
        link = saved.get(row['id'], {})
        data.append({'id': row['id'], '계좌': row['account'], '계좌유형': row['account_type'],
            '종목명': row['name'], '수량': row['quantity'], '매수금액(원)': row['cost'],
            '평가금액(원)': row['value'], '평가손익(원)': row['pnl'],
            '분석유형': link.get('kind', '미분류'), '종목코드': link.get('code', '')})
    st.subheader('잔고 확인 · 국내종목 연결')
    st.write('국내 상장 주식은 주식, 국내 상장 ETF는 ETF로 선택한 뒤 코드 확인 버튼을 누르세요. 펀드·채권·해외종목·현금은 미분류로 두어도 원본 표에 보존됩니다.')
    edited = st.data_editor(data, hide_index=True, use_container_width=True,
        key='samsung_editor_'+selected+'_'+str(st.session_state.get(version_key, 0)),
        column_order=['계좌', '계좌유형', '종목명', '수량', '매수금액(원)', '평가금액(원)', '평가손익(원)', '분석유형', '종목코드'],
        disabled=['id', '계좌', '계좌유형', '종목명', '수량', '매수금액(원)', '평가금액(원)', '평가손익(원)'],
        column_config={'분석유형': st.column_config.SelectboxColumn(options=['미분류', '주식', 'ETF'], required=True),
                       '종목코드': st.column_config.TextColumn(help='숫자 6자리. 비워두면 종목명으로 검색합니다.')})
    links = {row['id']: {'kind': row['분석유형'], 'code': str(row.get('종목코드') or '').strip()}
             for row in edited}
    st.session_state[links_key] = links
    if st.button('국내종목 코드 찾기·확인', disabled=not has_price_key):
        provider = provider_factory()
        found = dict(verified)
        cache = {}
        for row in report['positions']:
            link = links[row['id']]
            if link['kind'] not in ('주식', 'ETF'):
                continue
            try:
                key = (row['name'], link['code'])
                if key not in cache:
                    code = link['code']
                    if code:
                        if not re.fullmatch(r'[0-9]{6}', code):
                            raise SamsungError('종목코드는 숫자 6자리로 입력하세요.')
                        _, _, name = provider.price(code, date.fromisoformat(report['asof']))
                        if compact(name) != compact(row['name']):
                            raise SamsungError('입력한 코드의 종목명과 원본 종목명이 다릅니다.')
                    else:
                        matches = [m for m in provider.search_prices(row['name'])
                                   if compact(m['name']) == compact(row['name'])]
                        if len(matches) != 1:
                            raise SamsungError('종목명이 정확히 일치하는 코드가 하나로 확인되지 않습니다.')
                        code = matches[0]['code']
                    cache[key] = code
                link['code'] = cache[key]
                found[row['id']] = link['kind']+':'+link['code']
            except (DataError, SamsungError) as exc:
                found.pop(row['id'], None)
                st.warning(f"{row['name']} · {exc}")
        st.session_state[links_key] = links
        st.session_state[verified_key] = found
        st.session_state[version_key] = st.session_state.get(version_key, 0)+1
        st.session_state['samsung_lookup_done_'+selected] = True
        # Keep warnings visible on this run; the next interaction rebuilds the editor.
        verified = found
    if not has_price_key:
        st.caption('종목코드 검색·확인은 08 데이터 연결의 공공데이터포털 키가 필요합니다.')
    for identity, link in links.items():
        link['verified'] = verified.get(identity) == link['kind']+':'+link['code']
    snapshot = domestic_snapshot(report, links)
    st.subheader('확인된 국내 주식·ETF')
    if not snapshot['positions']:
        st.info('국내 주식·ETF를 분류하고 종목코드를 확인하면 통합 화면과 실적 조회에 연결됩니다.')
        st.caption('파일과 연결 정보는 현재 로그인 세션에 보관됩니다. 새 접속에서는 파일을 다시 올려주세요.')
        return
    # Show lookup outcomes without relying on a rerendered widget.
    st.dataframe([{'종목명': p['name'], '코드': p['code'], '유형': p['asset_kind'],
                   '수량': p['quantity'], '평가금액(원)': p['value']} for p in snapshot['positions']],
        hide_index=True, use_container_width=True)
    reports_key = 'samsung_dart_'+selected
    errors_key = 'samsung_dart_errors_'+selected
    if st.button('확인된 주식 실적·공시 조회', disabled=not has_dart_key):
        provider = provider_factory()
        financials, errors = {}, {}
        with st.spinner('확인된 국내 주식의 DART 자료를 조회합니다…'):
            for position in snapshot['positions']:
                if position['asset_kind'] != '주식':
                    continue
                try:
                    financials[position['code']] = provider.holding_report(position['code'])
                except DataError as exc:
                    errors[position['code']] = str(exc)
        st.session_state[reports_key] = financials
        st.session_state[errors_key] = errors
    financials = {code: r for code, r in st.session_state.get(reports_key, {}).items()
                  if any(p['code'] == code and p['asset_kind'] == '주식' for p in snapshot['positions'])}
    for code, reason in st.session_state.get(errors_key, {}).items():
        st.warning(f'{code} · {reason}')
    for code, result in financials.items():
        for source, reason in result.get('errors', {}).items():
            st.caption(f'{code} · {source} · {reason}')
    kis = st.session_state.get('snapshot')
    if kis and kis.get('mode') == 'real':
        if st.checkbox('선택한 명의자의 삼성증권 잔고와 현재 KIS 실전 잔고를 합산해 보기', key='samsung_combine_'+selected):
            snapshot = combine_with_kis(snapshot, kis)
            financials = {**st.session_state.get('reports', {}), **financials}
    st.caption(f"국내 주식·ETF의 확인된 행만 표시 · {snapshot['fetched']} · 매수원가는 원본 매수금액/수량 · 파일 가격은 자동 갱신되지 않습니다.")
    st.html(compact_dashboard(snapshot, financials,
        reason='이 잔고 파일에는 개별 매수 체결 이력이 없습니다.',
        holding_source='삼성증권 파일 기준 '+report['asof']+' · KIS 합산 선택 시 각 출처의 조회일 적용'))
    st.caption('ETF는 기업 실적 조회에서 제외합니다. 펀드·채권·해외종목·현금은 위 원본 표에만 표시합니다. 파일은 현재 세션에 보관되며 새 접속 시 다시 업로드해야 합니다.')
