"""Bounded IPO subscription source audit; market study requires a separate freeze."""
import argparse
import csv
from collections import Counter
from datetime import date
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from research_runtime import atomic_json, exclusive_lock, sha256
from source_checkpoint import package_sources, readback
from tender_preflight import verified_records
from research_reassessment import verified_bundle

ROOT=Path('inputs/ipo_screen_20261019')
OUT=Path('deliverables/ipo_screen_20261019')
POLICY=Path('configs/ipo_screen_protocol_20261019.json')
FIELDS=['序號','抽籤日期','證券名稱','證券代號','發行市場','申購開始日','申購結束日','承銷股數','實際承銷股數','承銷價(元)','實際承銷價(元)','撥券日期(上市、上櫃日期)','主辦券商','申購股數','總承銷金額(元)','總合格件','中籤率(%)','取消公開抽籤']


def roc(value):
    p=value.split('/')
    if len(p)!=3 or len(p[0])!=3:
        raise ValueError('Unexpected ROC date')
    return date(int(p[0])+1911,int(p[1]),int(p[2])).isoformat()


def number(value):
    value=str(value).strip()
    if value in ['','---','未訂出','--']:
        return None
    if not re.fullmatch(r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?',value):
        raise ValueError('Malformed numeric source field')
    result=Decimal(value.replace(',',''))
    if not result.is_finite() or result<0:
        raise ValueError('Nonfinite/negative quantity')
    return result


def parse_year(body,year):
    x=json.loads(body)
    if x.get('stat')!='OK' or str(x.get('date'))!=str(year) or [f.strip() for f in x.get('fields',[])]!=FIELDS or x.get('total')!=len(x.get('data',[])):
        raise ValueError('Wrong year/schema/count; HTTP200 is insufficient')
    rows=x['data']
    if not rows or any(len(r)!=18 or r[0]!=str(i) or not roc(r[1]).startswith(str(year)+'-') for i,r in enumerate(rows,1)):
        raise ValueError('Year/sequence/row width mismatch')
    return rows


def reconcile_csv(body,rows):
    csvrows=list(csv.reader(io.StringIO(body.decode('cp950'))))
    headers=[i for i,r in enumerate(csvrows) if [c.strip() for c in r[:18]]==FIELDS]
    if len(headers)!=1:
        raise ValueError('CSV header mismatch')
    data=[r for r in csvrows[headers[0]+1:] if r and r[0].isdigit()]
    if any(len(r)!=19 or r[-1]!='' for r in data) or [r[:18] for r in data]!=rows:
        raise ValueError('CSV/JSON row mismatch')


def source_audit():
    entry=verified('entry');data=verified('years')
    rows=parse_year(data['raw/2024.json'],2024)
    other=parse_year(data['raw/2023.json'],2023)
    reconcile_csv(data['raw/2024.csv'],rows)
    if data['raw/2024.json']==data['raw/2023.json']:
        raise ValueError('Year control is identical')
    cases=[]
    for r in rows:
        if r[4]!='初上市':
            continue
        if not r[3].isdigit() or len(r[3])!=4:
            raise ValueError('Unexpected domestic initial-listing identifier')
        cases.append(dict(symbol=r[3],name=r[2],draw_date=roc(r[1]),application_start=roc(r[5]),application_end=roc(r[6]),listing_date=roc(r[11]),reported_fields=dict(zip(FIELDS,r))))
    if len({(r['symbol'],r['draw_date']) for r in cases})!=len(cases):
        raise ValueError('Duplicate IPO event')
    atomic_json(OUT/'source_audit.json',dict(status='current_historical_table_verified_not_historical_pit',rows_2024=len(rows),rows_2023=len(other),csv_json_rows_verified=len(rows),market_categories=dict(Counter(r[4] for r in rows)),cohort_rows=len(cases),source_sha256=hashlib.sha256(data['raw/2024.json']).hexdigest(),historical_pit_verified=False,fee_scenario_source_sha256=hashlib.sha256(entry['raw/fees.html']).hexdigest()))
    atomic_json(OUT/'cases.json',cases)


CALCULATION=Path('configs/ipo_screen_calculation_protocol_20261019.json')


def calculation_policy():
    policy();c=json.loads(CALCULATION.read_text())
    if sha256(CALCULATION)!=json.loads((OUT/'calculation_freeze.json').read_text())['protocol_sha256'] or sha256(OUT/'cases.json')!=c['case_list_sha256'] or sha256(OUT/'source_audit.json')!=c['source_audit_sha256']:
        raise ValueError('Frozen calculation/cohort drift')
    return c


def terms(case,c):
    f=case['reported_fields'];issues=[]
    price=number(f['承銷價(元)']);actual=number(f['實際承銷價(元)']);lot=number(f['申購股數'])
    shares=number(f['實際承銷股數']);qualified=number(f['總合格件']);reported=number(f['中籤率(%)'])
    if f['取消公開抽籤'].strip():issues.append('cancelled_or_special_status')
    if price is None or price<=0 or lot is None or lot<=0:issues.append('unknown_price_or_lot')
    if actual is None or actual!=price:issues.append('unknown_or_changed_final_price')
    reservation=None if price is None or lot is None else price*lot+Decimal(c['application_fee_scenario'])+Decimal(c['winner_fee_scenario'])
    affordable=reservation is not None and reservation<=Decimal(c['single_application_budget_twd'])
    probability=None
    if shares is None or qualified is None or qualified<=0 or lot is None or lot<=0:
        issues.append('unknown_allocation_terms')
    elif shares%lot!=0 or lot!=lot.to_integral_value() or qualified!=qualified.to_integral_value():
        issues.append('noninteger_allocation')
    else:
        probability=min(Decimal(1),shares/lot/qualified)
        if reported is None or abs(probability*100-reported)>Decimal('0.01'):
            issues.append('published_probability_inconsistent')
    if not case['application_start']<=case['application_end']<case['draw_date']<=case['listing_date']:
        issues.append('inconsistent_dates')
    return dict(offer_price=str(price) if price is not None else None,lot_size=str(lot) if lot is not None else None,
                reservation_scenario_twd=str(reservation) if reservation is not None else None,
                individually_affordable=affordable,allocation_probability=str(probability) if probability is not None else None,issues=issues)


def expected_amount(price,lot,probability,opening,drag,application_fee,winner_fee):
    values=[Decimal(str(v)) for v in [price,lot,probability,opening,drag,application_fee,winner_fee]]
    price,lot,p,opening,drag,a,w=values
    if any(not v.is_finite() for v in values) or not 0<=p<=1 or not 0<=drag<1 or min(price,lot,opening)<=0 or min(a,w)<0:
        raise ValueError('Invalid expected-value inputs')
    return p*(lot*(opening*(1-drag)-price)-w)-a


def overlap_through_listing(rows):
    dates={r['application_end'] for r in rows}
    return max((sum(Decimal(r['terms']['reservation_scenario_twd']) for r in rows if r['application_end']<=d<=r['listing_date']) for d in dates),default=Decimal(0))


def match_quotes():
    import pandas as pd
    c=calculation_policy();manifest=verified_bundle(c['raw_price_archive'],c['raw_price_archive_sha256'])
    if manifest[c['raw_price_member']]!=c['raw_price_member_sha256']:
        raise ValueError('Frozen market member differs')
    cases=json.loads((OUT/'cases.json').read_text());keys={(r['symbol'],r['listing_date']) for r in cases};quotes={}
    with zipfile.ZipFile(c['raw_price_archive']) as z,z.open(c['raw_price_member']) as source:
        for chunk in pd.read_csv(source,compression='gzip',usecols=['symbol','date','open','close'],dtype=str,chunksize=200000):
            selected=chunk[chunk.symbol.isin({k[0] for k in keys})]
            for r in selected.itertuples(index=False):
                k=(r.symbol,r.date)
                if k not in keys:continue
                if k in quotes:raise ValueError('Duplicate exact market endpoint')
                quotes[k]=dict(open=r.open,close=r.close)
    result=[]
    for case in cases:
        t=terms(case,c);q=quotes.get((case['symbol'],case['listing_date']))
        if q is None:
            t['issues'].append('missing_exact_listing_quote')
        else:
            try:
                if any(number(q[k]) is None or number(q[k])<=0 for k in ['open','close']):
                    raise ValueError('Invalid quote')
            except Exception:
                t['issues'].append('invalid_exact_listing_quote')
        result.append(dict(**case,terms=t,raw_listing_quote=q,eligible_for_calculation=t['individually_affordable'] and not t['issues']))
    atomic_json(OUT/'matched_cases.json',result)
    atomic_json(OUT/'market_receipt.json',dict(archive_sha256=c['raw_price_archive_sha256'],member_sha256=c['raw_price_member_sha256'],crc_manifest_verified=True,exact_quote_matches=len(quotes),events=len(cases),no_endpoint_shifting=True,raw_open_close_only=True,new_price_downloads=0))


def calculate():
    c=calculation_policy();rows=json.loads((OUT/'matched_cases.json').read_text())
    eligible=[r for r in rows if r['eligible_for_calculation']]
    scenario_rows=[];summary=[]
    for drag in c['sale_drag_scenarios']:
        amounts=[]
        for r in eligible:
            t=r['terms'];amount=expected_amount(t['offer_price'],t['lot_size'],t['allocation_probability'],r['raw_listing_quote']['open'],drag,c['application_fee_scenario'],c['winner_fee_scenario'])
            scenario_rows.append(dict(symbol=r['symbol'],draw_date=r['draw_date'],sale_drag=drag,expected_application_twd=str(amount)))
            amounts.append(amount)
        ordered=sorted(amounts);n=len(ordered)
        median=None if not n else ordered[n//2] if n%2 else (ordered[n//2-1]+ordered[n//2])/2
        summary.append(dict(sale_drag=drag,applications=n,sum_expected_twd=str(sum(amounts)),median_expected_twd=str(median) if median is not None else None,positive_applications=sum(v>0 for v in amounts)))
    probs=[Decimal(r['terms']['allocation_probability']) for r in eligible];product=Decimal(1)
    for p in probs:product*=1-p
    # Diagnostic only: no selection or funding adaptation follows draw outcomes.
    reservation_peak=overlap_through_listing(eligible)
    coverage=all(r['terms']['individually_affordable'] or r['terms']['reservation_scenario_twd'] is not None for r in rows) and all(not r['terms']['issues'] for r in rows if r['terms']['individually_affordable'])
    survives=coverage and bool(eligible) and all(Decimal(v['sum_expected_twd'])>0 and Decimal(v['median_expected_twd'])>0 for v in summary)
    atomic_json(OUT/'expected_amounts.json',scenario_rows)
    atomic_json(OUT/'summary.json',dict(status='retrospective_conditional_per_application_quote_proxy_only',cohort_events=len(rows),individually_affordable_events=sum(r['terms']['individually_affordable'] for r in rows),calculated_events=len(eligible),whole_eligible_cohort_coverage=coverage,scenarios=summary,
        no_win_probability_lower_bound_union=str(max(Decimal(0),1-sum(probs))),independent_lottery_no_win_probability_illustration=str(product),
        no_win_application_fee_loss_twd=str(-Decimal(c['application_fee_scenario'])*len(eligible)),
        reservation_overlap_through_listing_twd=str(reservation_peak),
        reservation_overlap_through_listing_within_budget=reservation_peak<=Decimal(c['single_application_budget_twd']),
        reservation_diagnostic_scope='Application deadline through listing date inclusive; refunds, sale settlement and reinvestment are not modeled. Passing this is not executable funding proof.',
        funded_portfolio_simulated=False,fee_versions_2024_verified=False,historical_pit_verified=False,actual_fills_verified=False,
        exploratory_resource_gate_passed=survives,profit_edge_proven=False,manual_daily_validation=False,valid_prospective_signals=0,
        decision='survives_narrow_historical_screen_no_deployment' if survives else 'close_fixed_screen_without_tuning',
        interpretation='Expected amounts are conditional on observed future IPO quotes and realized applications; not a forecast or account profit. Unknown cases remain gaps, overlap funding not modeled.'))


def policy():
    if sha256(POLICY)!=json.loads((OUT/'protocol_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Frozen IPO source protocol drift')
    return json.loads(POLICY.read_text())


def package(tag):
    policy()
    cfgpath=Path('configs/ipo_screen_'+tag+'_sources.json')
    cfg=json.loads(cfgpath.read_text());raw=ROOT/('raw_'+tag)
    results=json.loads((raw/'results.json').read_text())
    if results['config_sha256']!=sha256(cfgpath):
        raise ValueError('Acquisition config differs')
    verified_records(cfg,results,lambda n:(raw/n).read_bytes())
    entries={'protocol.json':POLICY,'requests.json':cfgpath}
    entries.update({'raw/'+p.name:p for p in raw.iterdir() if p.is_file()})
    with exclusive_lock(ROOT/'acquisition.lock'):
        package_sources(ROOT,OUT,tag,entries)


def verified(tag):
    policy();pkg,transfer=readback(OUT,tag)
    cfgpath=Path('configs/ipo_screen_'+tag+'_sources.json')
    with zipfile.ZipFile(pkg['retrieved']) as z:
        data={n:z.read(n) for n in z.namelist()}
    for name,p in [('protocol.json',POLICY),('requests.json',cfgpath)]:
        if hashlib.sha256(data[name]).hexdigest()!=sha256(p):
            raise ValueError('Archived policy/requests differ')
    results=json.loads(data['raw/results.json'])
    if results['config_sha256']!=sha256(cfgpath):
        raise ValueError('Archived source config differs')
    records=verified_records(json.loads(cfgpath.read_text()),results,lambda n:data['raw/'+n])
    atomic_json(OUT/(tag+'_source_receipt.json'),dict(archive_sha256=pkg['sha256'],manifest_files=pkg['manifest_files'],roundtrip_verified=True,crc_manifest_verified=True,backup=transfer,
        observations=[dict(request=r['request'],http_status=r.get('http_status'),exit_code=r.get('exit_code'),sha256=r.get('sha256'),size_bytes=r.get('size_bytes'),request_started_at=r.get('request_started_at'),observed_at=r.get('observed_at'),transport_stderr=r.get('stderr') if r.get('exit_code')!=0 else '') for r in records]))
    return data


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['package','verify','source_audit','match_quotes','calculate']);p.add_argument('--tag',default='entry');args=p.parse_args()
    if args.stage=='source_audit':source_audit()
    elif args.stage=='package':package(args.tag)
    elif args.stage=='verify':verified(args.tag)
    else:globals()[args.stage]()
