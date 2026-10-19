"""Fixed-parameter2025 temporal replication; never rewrites the frozen2024 screen."""
import argparse
from collections import Counter
import csv
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import zipfile

from ipo_screen import FIELDS, expected_amount, number, parse_year, reconcile_csv, roc, terms
from research_reassessment import verified_bundle
from research_runtime import atomic_json, exclusive_lock, sha256
from source_checkpoint import package_sources, readback
from tender_preflight import verified_records

ROOT=Path('inputs/ipo_replication_20261020')
OUT=Path('deliverables/ipo_replication_20261020')
POLICY=Path('configs/ipo_replication_protocol_20261020.json')
SOURCES=Path('configs/ipo_replication_sources.json')


def policy():
    p=json.loads(POLICY.read_text())
    if sha256(POLICY)!=json.loads((OUT/'protocol_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Frozen2025protocol drift')
    if sha256(SOURCES)!=p['source_requests_sha256'] or sha256(Path('ipo_screen.py'))!=p['frozen_functions_sha256']:
        raise ValueError('Frozen source requests or prior calculation code drift')
    if sha256(Path(p['calendar_path']))!=p['calendar_sha256']:
        raise ValueError('Frozen observed market calendar drift')
    for path,digest in p['prior_checkpoints'].items():
        if sha256(Path(path))!=digest:raise ValueError('Prior checkpoint drift')
        for file,h in json.loads(Path(path).read_text())['files'].items():
            if sha256(Path(file))!=h:raise ValueError('Prior frozen output drift: '+file)
    return p


def package():
    p=policy();cfg=json.loads(SOURCES.read_text());raw=ROOT/'raw'
    if len(cfg['requests'])>p['request_bound']:raise ValueError('Request budget exceeded')
    result=json.loads((raw/'results.json').read_text())
    if result['config_sha256']!=sha256(SOURCES):raise ValueError('Acquisition request drift')
    verified_records(cfg,result,lambda name:(raw/name).read_bytes())
    entries={'protocol.json':POLICY,'requests.json':SOURCES}
    entries.update({'raw/'+path.name:path for path in raw.iterdir() if path.is_file()})
    with exclusive_lock(ROOT/'acquisition.lock'):package_sources(ROOT,OUT,'sources',entries)


def cohort(rows,year,category):
    cases=[]
    for r in rows:
        if r[4]!=category:continue
        if not r[3].isdigit() or len(r[3])!=4:raise ValueError('Unexpected domestic identifier')
        cases.append(dict(symbol=r[3],name=r[2],draw_date=roc(r[1]),application_start=roc(r[5]),application_end=roc(r[6]),listing_date=roc(r[11]),reported_fields=dict(zip(FIELDS,r))))
    if not cases or any(not r['draw_date'].startswith(str(year)+'-') for r in cases) or len({(r['symbol'],r['draw_date']) for r in cases})!=len(cases):
        raise ValueError('Empty, duplicate or wrong-year cohort')
    return cases


def source_audit():
    p=policy();pkg,transfer=readback(OUT,'sources')
    with zipfile.ZipFile(pkg['retrieved']) as z:data={name:z.read(name) for name in z.namelist()}
    for name,path in [('protocol.json',POLICY),('requests.json',SOURCES)]:
        if hashlib.sha256(data[name]).hexdigest()!=sha256(path):raise ValueError('Archived configuration drift')
    results=json.loads(data['raw/results.json']);cfg=json.loads(SOURCES.read_text())
    if results['config_sha256']!=sha256(SOURCES):raise ValueError('Archived source request drift')
    records=verified_records(cfg,results,lambda name:data['raw/'+name])
    if any(r.get('http_status')!=200 or r.get('exit_code')!=0 for r in records):raise ValueError('Source transport failed; archived failures are not usable tables')
    rows=parse_year(data['raw/2025.json'],p['draw_year']);reconcile_csv(data['raw/2025.csv'],rows)
    cases=cohort(rows,p['draw_year'],p['market_category'])
    atomic_json(OUT/'cases.json',cases)
    atomic_json(OUT/'source_receipt.json',dict(archive_sha256=pkg['sha256'],manifest_files=pkg['manifest_files'],sha_crc_manifest_verified=True,backup=transfer,
        rows=len(rows),categories=dict(Counter(r[4] for r in rows)),cohort_events=len(cases),csv_json_all_rows_identical=True,historical_pit_verified=False,
        source_observations=[{k:r.get(k) for k in ['request','http_status','exit_code','size_bytes','sha256','request_started_at','observed_at']} for r in records]))


def match():
    import pandas as pd
    p=policy();receipt=json.loads((OUT/'source_receipt.json').read_text())
    if not receipt['sha_crc_manifest_verified'] or not receipt.get('semantic_consistency_passed',receipt.get('csv_json_all_rows_identical',False)):
        raise ValueError('Verified readback AND semantic source consistency required before market endpoints')
    manifest=verified_bundle(p['raw_price_archive'],p['raw_price_archive_sha256'])
    if manifest[p['raw_price_member']]!=p['raw_price_member_sha256']:raise ValueError('Frozen raw-price member differs')
    cases=json.loads((OUT/'cases.json').read_text());keys={(r['symbol'],r['listing_date']) for r in cases};symbols={s for s,d in keys};quotes={}
    with zipfile.ZipFile(p['raw_price_archive']) as z,z.open(p['raw_price_member']) as body:
        for chunk in pd.read_csv(body,compression='gzip',usecols=['symbol','date','open','close'],dtype=str,chunksize=200000):
            for r in chunk[chunk.symbol.isin(symbols)].itertuples(index=False):
                key=(r.symbol,r.date)
                if key not in keys:continue
                if key in quotes:raise ValueError('Duplicate exact quote')
                quotes[key]=dict(open=r.open,close=r.close)
    matched=[]
    for r in cases:
        t=terms(r,p);q=quotes.get((r['symbol'],r['listing_date']))
        if q is None:t['issues'].append('missing_exact_listing_quote')
        elif any(number(q[k]) is None or number(q[k])<=0 for k in ['open','close']):t['issues'].append('invalid_exact_listing_quote')
        matched.append(dict(**r,terms=t,raw_listing_quote=q,eligible_for_calculation=t['individually_affordable'] and not t['issues']))
    atomic_json(OUT/'matched_cases.json',matched)
    atomic_json(OUT/'market_receipt.json',dict(archive_sha256=p['raw_price_archive_sha256'],member_sha256=p['raw_price_member_sha256'],crc_manifest_verified=True,
        exact_listing_quote_matches=len(quotes),events=len(cases),new_price_downloads=0,endpoint_shifting=False))


def analytical_funding(rows,calendar,drag,a,w):
    """Worst initial capital over every binary outcome, independent of joint probabilities."""
    if len(set(calendar))!=len(calendar) or calendar!=sorted(calendar):raise ValueError('Duplicate/unordered calendar')
    index={d:i for i,d in enumerate(calendar)};events=[];dates=[]
    def later(day,lag):
        if day not in index or index[day]+lag>=len(calendar):raise ValueError('Missing or exhausted market calendar')
        return calendar[index[day]+lag]
    for i,r in enumerate(rows):
        if r['application_end'] not in index:raise ValueError('Nonmarket application deadline')
        principal=Fraction(r['terms']['offer_price'])*Fraction(r['terms']['lot_size']);sale=Fraction(r['raw_listing_quote']['open'])*Fraction(r['terms']['lot_size'])*(1-drag)
        refund=later(r['draw_date'],1);settled=later(r['listing_date'],2)
        events += [(r['application_end'],0,i,-principal-a-w,Fraction(0)),(refund,1,i,principal+w,-principal-w),(settled,1,i,Fraction(0),sale)]
        dates.append(dict(symbol=r['symbol'],reserve=r['application_end'],refund_if_loss=refund,sale_if_win=settled))
    base=Fraction(0);coefficients=[Fraction(0)]*len(rows);minimum=Fraction(0);witness=None
    for day,phase,i,delta,coefficient in sorted(events):
        base+=delta;coefficients[i]+=coefficient
        lower=base+sum((min(Fraction(0),v) for v in coefficients),Fraction(0))
        if lower<minimum:
            minimum=lower;witness=dict(date=day,phase=phase,won_symbols=[rows[j]['symbol'] for j,v in enumerate(coefficients) if v<0])
    return dict(maximum_required_initial_cash_exact=str(-minimum),within_300k=-minimum<=300000,witness=witness,dates=dates,
        scope='All binary win paths under declared marketday/refund/settlement scenario; not verified banking or fills')


def summarize(rows,p):
    eligible=[r for r in rows if r['eligible_for_calculation']]
    gaps=[dict(symbol=r['symbol'],issues=r['terms']['issues']) for r in rows if r['terms']['individually_affordable'] and r['terms']['issues']]
    unknown_budget=[r['symbol'] for r in rows if r['terms']['reservation_scenario_twd'] is None]
    complete=bool(eligible) and not gaps and not unknown_budget
    details=[];scenarios=[]
    for drag in p['sale_drag_scenarios']:
        amounts=[]
        for r in eligible:
            t=r['terms'];value=expected_amount(t['offer_price'],t['lot_size'],t['allocation_probability'],r['raw_listing_quote']['open'],drag,p['application_fee_scenario'],p['winner_fee_scenario'])
            amounts.append(value);details.append(dict(symbol=r['symbol'],sale_drag=drag,expected_twd=str(value)))
        ordered=sorted(amounts);n=len(ordered);median=None if not n else ordered[n//2] if n%2 else (ordered[n//2-1]+ordered[n//2])/2
        scenarios.append(dict(sale_drag=drag,calculated_events=n,partial_sum_twd=str(sum(amounts)),whole_eligible_cohort_sum_twd=str(sum(amounts)) if complete else None,
            median_expected_twd=str(median) if median is not None else None,positive_events=sum(v>0 for v in amounts),negative_events=sum(v<0 for v in amounts)))
    gate=None if not complete else all(Decimal(s['whole_eligible_cohort_sum_twd'])>0 and Decimal(s['median_expected_twd'])>0 for s in scenarios)
    return details,dict(cohort_events=len(rows),calculated_events=len(eligible),whole_affordable_cohort_coverage=complete,gaps=gaps,unknown_budget_symbols=unknown_budget,
        exploratory_resource_gate_passed=gate,scenarios=scenarios,status='incomplete_coverage' if gate is None else 'positive_2025_temporal_replication' if gate else 'fixed_2025_replication_failed_gate')


def calculate():
    p=policy();receipt=json.loads((OUT/'source_receipt.json').read_text())
    if not receipt.get('semantic_consistency_passed',receipt.get('csv_json_all_rows_identical',False)):
        raise ValueError('Source inconsistency blocks calculation, including stale local matched cases')
    rows=json.loads((OUT/'matched_cases.json').read_text());details,summary=summarize(rows,p)
    with gzip.open(p['calendar_path'],'rt') as f:calendar=[r['date'] for r in csv.DictReader(f)]
    eligible=[r for r in rows if r['eligible_for_calculation']]
    funding=[dict(sale_drag=drag,**analytical_funding(eligible,calendar,Fraction(drag),Fraction(p['application_fee_scenario']),Fraction(p['winner_fee_scenario']))) for drag in p['sale_drag_scenarios']]
    probabilities=[Fraction(r['reported_fields']['實際承銷股數'].replace(',',''))/Fraction(r['reported_fields']['申購股數'].replace(',',''))/Fraction(r['reported_fields']['總合格件'].replace(',','')) for r in eligible]
    probabilities=[min(Fraction(1),v) for v in probabilities];product=Fraction(1)
    for prob in probabilities:product*=1-prob
    summary.update(funding=funding,funding_scope='Whole fixed affordable cohort' if summary['whole_affordable_cohort_coverage'] else 'Partial diagnostic subset only; missing cases unresolved',
        no_win_probability_lower_bound_exact=str(max(Fraction(0),1-sum(probabilities))),independent_no_win_illustration_exact=str(product),no_win_fee_loss_twd=str(-len(eligible)*Fraction(p['application_fee_scenario'])),
        original_2024_gate_preserved=True,year_2025_is_untouched_holdout=False,historical_pit_verified=False,actual_fills_verified=False,valid_prospective_signal_date=None,
        decision='Prepare low-work as-of evidence capture if positive; never daily human validation or trades' if summary['exploratory_resource_gate_passed'] else 'Preserve failure or gap without changing parameters or searching another year')
    atomic_json(OUT/'expected_amounts.json',details);atomic_json(OUT/'summary.json',summary)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['package','source_audit','match','calculate']);globals()[parser.parse_args().stage]()
