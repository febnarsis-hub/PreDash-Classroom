"""Compact evidence graphics. Every mark comes from supplied account/report data."""
import html
from math import isfinite

PALETTE=('#214b3a','#a68137','#71876b','#537684','#b3b9a0','#d1d4c4')

def esc(value):return html.escape(str(value),quote=True)

def panel(title,body,note=''):
    return f"<section class='pd-v-panel'><h3>{esc(title)}</h3>{body}<div class='pd-v-note'>{esc(note)}</div></section>"

def empty(message):return f"<div class='pd-v-empty'>{esc(message)}</div>"

def signed(value,suffix='원'):
    cls='pd-plus' if value>0 else 'pd-minus' if value<0 else 'pd-muted'
    return f"<span class='{cls}'>{value:+,.0f}{esc(suffix)}</span>"

def allocation(positions):
    if not positions:return empty('계좌 조회 후 보유 비중 표시')
    ranked=sorted(positions,key=lambda p:-p['weight'])
    groups=[(p['name'],max(0,float(p['weight']))) for p in ranked[:5]]
    rest=sum(max(0,float(p['weight'])) for p in ranked[5:])
    if rest:groups.append(('기타',rest))
    total=sum(w for _,w in groups)
    if total<=0:return empty('평가액이 없어 비중 산출 보류')
    start=0;segments=[];legend=[]
    for i,(name,weight) in enumerate(groups):
        stop=start+weight/total*100;color=PALETTE[i]
        segments.append(f'{color} {start:.4f}% {stop:.4f}%');start=stop
        legend.append(f"<div class='pd-v-legend'><i style='background:{color}'></i><span>{esc(name)}</span><b>{weight:.1f}%</b></div>")
    return (f"<div class='pd-v-allocation'><div class='pd-v-donut' role='img' aria-label='국내주식 평가액 기준 보유 비중' style='background:conic-gradient({','.join(segments)})'>"
            f"<div><b>{len(positions)}</b><span>보유종목</span></div></div><div>{''.join(legend)}</div></div>")

def annual_bars(years,key,label):
    values=[]
    for year in years[-3:]:
        raw=year.get(key)
        if raw is None:continue
        value=float(raw)
        if not isfinite(value):continue
        values.append((str(year['year']),value))
    if len(values)<2:return empty(label+' 비교 자료 부족')
    # Both zero and negative figures share a true zero baseline.
    lo=min(0,min(v for _,v in values));hi=max(0,max(v for _,v in values));span=hi-lo or 1
    top,bottom=25,112;baseline=top+hi/span*(bottom-top)
    bars=[];text=[]
    for i,(year,value) in enumerate(values):
        x=35+i*95;y=top+(hi-value)/span*(bottom-top);height=abs(y-baseline)
        color='#1b5ca0' if value<0 else '#214b3a' if key=='revenue' else '#a68137'
        bars.append(f"<rect x='{x}' y='{min(y,baseline):.2f}' width='42' height='{height:.2f}' rx='2' fill='{color}'/><text x='{x+21}' y='{y-6 if value>=0 else y+15:.2f}' text-anchor='middle'>{value:,.1f}</text><text x='{x+21}' y='150' text-anchor='middle'>{esc(year)}</text>")
        text.append(f'{year}년 {value:,.1f}억')
    return (f"<div class='pd-v-chart'><div class='pd-v-chart-title'>{esc(label)} <small>억원</small></div><svg class='pd-v-bars' viewBox='0 0 {len(values)*95+25} 166' role='img' aria-label='{esc(label+": "+", ".join(text))}'>"
            f"<line x1='15' y1='{baseline:.2f}' x2='{len(values)*95+10}' y2='{baseline:.2f}' stroke='#aeb8a7'/>{''.join(bars)}</svg></div>")

def compact_dashboard(snapshot,reports,matching=None,reason='체결 조회 후 가격 위치 표시',portfolio_only=False,holding_source=None):
    positions=sorted(snapshot.get('positions',[]),key=lambda p:-p['weight'])
    rows=[]
    for p in positions[:5]:
        rows.append(f"<tr><td><b>{esc(p['name'])}</b><small>{esc(p['code'])} · {p['quantity']:g}주</small></td><td>{p['value']:,.0f}</td><td>{signed(p['pnl'],'')}</td><td>{p['weight']:.1f}%</td></tr>")
    holdings=("<div class='pd-v-table-wrap'><table class='pd-v-table'><thead><tr><th>종목 / 수량</th><th>평가액 · 원</th><th>평가손익 · 원</th><th>비중</th></tr></thead><tbody>"+''.join(rows)+"</tbody></table></div>") if rows else empty('계좌를 불러오면 보유종목이 표시됩니다.')
    holding_note=f'평가액 순 상위 5개 · 전체 {len(positions)}종목은 내 계좌에서 확인' if len(positions)>5 else '한국투자증권 잔고 · 조회 시점 기준'
    if holding_source is not None:holding_note=holding_source
    top="<div class='pd-v-top'>"+panel('보유종목 한눈에',holdings,holding_note)+panel('자산 배분',allocation(positions),'국내주식 평가액 기준 · 현금·해외 제외')+"</div>"
    if portfolio_only:return top
    # Same financial source/basis per panel; never combine different companies.
    company=next((p for p in positions if reports.get(p['code'],{}).get('metrics') is not None),None)
    if company:
        report=reports[company['code']];m=report['metrics'];years=[{'year':str(m['year']-1)+' 동기','revenue':m['prior_revenue'],'profit':m['prior_profit']},{'year':str(m['year'])+' 누적','revenue':m['revenue'],'profit':m['profit']}]
        earnings=f"<div class='pd-v-company'>{esc(company['name'])}<small>1~{m['quarter']}분기 누적 · {esc(m['basis'])}</small></div><div class='pd-v-financial'>{annual_bars(years,'revenue','매출')}{annual_bars(years,'profit','영업이익')}</div>"
        earnings_note=f"OpenDART · 조회 {report.get('fetched','미확인')} · 두 그래프의 세로축 범위는 각각 적용"
    else:earnings=empty('최근 누적 동기 실적 자료 없음');earnings_note='공식 결산 자료 연결 후 표시'
    notices=[]
    for p in positions:
        for d in reports.get(p['code'],{}).get('disclosures',[]):notices.append((str(d.get('date','')),p['name'],d))
    notices.sort(key=lambda x:x[0],reverse=True)
    entries=[]
    for date,name,d in notices[:3]:
        # Never insert arbitrary provider links into our HTML.
        url=str(d.get('url',''))
        title=f"<b>{esc(d.get('title','공시'))}</b>"
        if url.startswith('https://dart.fss.or.kr/'):title=f"<a href='{esc(url)}' target='_blank' rel='noopener noreferrer'>{title}</a>"
        entries.append(f"<div class='pd-v-notice'><small>{esc(date)} · {esc(name)}</small>{title}</div>")
    disclosure=''.join(entries) or empty('수집된 공시 없음')
    if matching:
        pct=max(0,min(100,float(matching['position_pct'])))
        price=(f"<div class='pd-v-company'>{esc(matching['name'])}<small>매수 {matching['at'].date()}</small></div><div class='pd-v-price'>{matching['position_pct']:.0f}<small>%</small></div>"
               f"<div class='pd-range' style='--p:{pct:.1f}%'><span class='pd-dot'></span></div><div class='pd-v-scale'><span>저가 {matching['range_low']:,.0f}</span><span>고가 {matching['range_high']:,.0f}</span></div>")
        price_note=f"매수 전 20거래일 범위 · {matching['from']}~{matching['to']} · 실수 판정 아님"
    else:price=empty(reason);price_note='가격 위치는 매수 전 20거래일 범위 기준'
    return (top
            +"<div class='pd-v-bottom'>"+panel('실적 흐름',earnings,earnings_note)+panel('최근 수집 공시',disclosure,'접수일 기준 · 원문 확인')+panel('매수 가격 위치',price,price_note)+"</div>")
