"""Rebuild prospective matrices from a verified source archive, then independently rank.

No caller-supplied matrix can upgrade itself to raw_replay_verified.
"""
import argparse
import bisect
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import zipfile

import numpy as np
import pandas as pd
from lxml import html

from prospective_sources import verify_archive, calendar_days
from prospective_selection import FEATURES, RULES, METHODS, REQUIRED, select
from prospective_journal import TZ
from research_runtime import atomic_json, sha256, utcnow
from tpex_source_pilot import validate_quotes
from tpex_classification_pilot import parse_isin
from tpex_pool import classify
from tpex_event_features import institutional_five_days, revenue_acceleration, attach_revenue
from tpex_proxy_features import features
from tpex_flow_pilot import parse as parse_flow
from acquire_tpex_revenue import parse as parse_revenue
from audit_tpex_event_coverage import event_date, number
from twse_history.build_history import load_actions, adjust_prices, audit_events


def frozen():
    protocol = json.loads(Path('configs/tpex_prospective_protocol.json').read_text())
    for path, expected in protocol['frozen_source_git_blobs'].items():
        actual = subprocess.check_output(['git','hash-object',path],text=True).strip()
        if actual != expected:
            raise ValueError('Frozen implementation drift: '+path)
    return protocol


def independent_selection(frame, date):
    """Pure record ranking, independent of pandas selector sorting/filtering code."""
    rows = []
    for row in frame.to_dict('records'):
        if all(pd.notna(row[k]) and math.isfinite(float(row[k])) for k in FEATURES+RULES):
            rows.append(row)
    result = dict(signal_date=date, source_rows=len(frame), common_pool=len(rows), status='complete' if len(rows)>=100 else 'insufficient_pool', selections={})
    if len(rows)<100:
        return result
    count=math.ceil(len(rows)/10)
    for method in METHODS:
        if method in RULES:
            chosen=sorted(r['code'] for r in rows if r[method]==1)
        elif method=='all_three':
            chosen=sorted(r['code'] for r in rows if all(r[k]==1 for k in RULES))
        else:
            chosen=[r['code'] for r in sorted(rows,key=lambda r:(-r[method],r['code']))[:count]]
        result['selections'][method]=chosen
    return result


def next_entry(raw, date):
    doc=json.loads(raw)
    if doc.get('stat')!='ok' or doc.get('endDate')!=date[:4]+'0101' or not doc.get('data',{}).get('html'):
        raise ValueError('Official holiday schedule unavailable')
    # Every table row retains the source description; only explicit closed days excluded.
    text=html.fromstring(doc['data']['html'])
    closed=set()
    for tr in text.xpath('//tr'):
        cells=[' '.join(x.text_content().split()) for x in tr.xpath('./td|./th')]
        if not cells:continue
        line=' '.join(cells)
        if '開始交易' in line or '最後交易' in line:continue
        for month,day in re.findall(r'(\d{1,2})月\s*(\d{1,2})日',line):
            closed.add(dt.date(int(date[:4]),int(month),int(day)))
    if len(closed)<10 or str(int(date[:4])-1911) not in ' '.join(text.itertext()):
        raise ValueError('Unrecognized holiday year/schema')
    day=dt.date.fromisoformat(date)+dt.timedelta(days=1)
    while day.weekday()>=5 or day in closed:day+=dt.timedelta(days=1)
    return dt.datetime.combine(day,dt.time(9),TZ).isoformat()


def rebuild(root):
    protocol=frozen()
    receipt=json.loads((root/'checkpoint.json').read_text())
    if receipt.get('roundtrip_verified') is not True:raise ValueError('Source roundtrip missing')
    archive=Path(receipt['retrieved_path'])
    members=verify_archive(archive,receipt['sha256'])
    with zipfile.ZipFile(archive) as z:
        raw={n:z.read(n) for n in members}
    acquisition=json.loads(raw['acquisition.json']);date=acquisition['signal_date']
    observed=[]
    for key,body in raw.items():
        if not key.startswith('raw/') or key.endswith('.meta.json'):continue
        meta=json.loads(raw[key+'.meta.json'])
        if hashlib.sha256(body).hexdigest()!=meta['sha256']:raise ValueError('Raw metadata mismatch')
        stamp=dt.datetime.fromisoformat(meta['observed_at'])
        start=dt.datetime.fromisoformat(meta['request_started_at'])
        if stamp.tzinfo is None or start.tzinfo is None or start>stamp:raise ValueError('Invalid observation clock')
        if stamp.astimezone(TZ).date()>dt.date.fromisoformat(date):raise ValueError('Source arrived after signal day')
        observed.append(stamp)
    days=[]
    for name in sorted(n for n in raw if n.startswith('raw/calendar_') and not n.endswith('.meta.json')):
        days+=calendar_days(raw[name],Path(name).stem.removeprefix('calendar_'),date)
    if days!=acquisition['calendar_days'] or len(days)<61 or days[-1]!=date:raise ValueError('Calendar/warmup drift')
    clock=pd.DatetimeIndex(days)
    known={}
    for name in ('isin_otc.html','isin_listed.html'):
        for code,value in parse_isin(raw['raw/'+name]).items():
            if code in known and known[code]['cfi']!=value['cfi']:raise ValueError('Conflicting ISIN evidence')
            known.setdefault(code,value)
    quotes=[]
    for day in days:
        doc=json.loads(raw[f'raw/quote_{day}.json']);validate_quotes(doc,day)
        table=doc['tables'][0];fields=[x.strip().replace('<br>','') for x in table['fields']]
        for row in table['data']:
            r=dict(zip(fields,row));code=r['代號'];tier,cfi=classify(code,known,{})
            q=dict(date=day,code=code,type_evidence=tier,confirmed_subset=tier=='confirmed_ordinary',primary_pool=tier in ('confirmed_ordinary','ordinary_stock_rule_candidate'))
            for dest,src in [('open','開盤'),('high','最高'),('low','最低'),('close','收盤'),('volume_shares','成交股數')]:q[dest]=number(r[src])
            quotes.append(q)
    q=pd.DataFrame(quotes);lookup={(r['date'],r['code']):r for r in quotes};events=[]
    for kind in ('excal','reduction','change'):
        doc=json.loads(raw[f'raw/event_{kind}.json'])
        if doc.get('stat')!='ok' or doc.get('date')!=f'{date[:4]}0101~{date.replace("-", "")}':raise ValueError('Event source range differs')
        for table in doc['tables']:
            if len(table['data'])!=table['totalCount']:raise ValueError('Incomplete event table')
            for row in table['data']:
                day=event_date(row[0]);code=row[1]
                if day<days[0] or day>date:continue
                prior=next((lookup[(d,code)] for d in reversed(days[:bisect.bisect_left(days,day)]) if (d,code) in lookup and pd.notna(lookup[d,code]['close'])),None)
                last,ref=number(row[3]),number(row[4])
                status='last_close_matches' if prior and prior['close']==last else 'missing_or_mismatched_prior'
                if day not in days:status='event_date_outside_market_calendar'
                events.append(dict(event_date=day,code=code,official_last_close=last,official_reference=ref,status=status))
    q['date']=pd.to_datetime(q.date)
    parts=[]
    for code,group in q.groupby('code',sort=True):
        if group.primary_pool.any():parts.append(features(group,clock,[e for e in events if e['code']==code]))
    price=pd.concat(parts,ignore_index=True);price=price.loc[price.date.eq(date),['date','code']+FEATURES+['breakout60_volume15']].copy();price['date']=pd.to_datetime(price.date)
    flow=pd.concat([parse_flow(json.loads(raw[f'raw/flow_{d}.json']),d) for d in days[-6:-1]],ignore_index=True);flow['date']=pd.to_datetime(flow.date)
    flow_features=institutional_five_days(flow,clock[-6:]);base=price.merge(flow_features,on=['date','code'],how='left',validate='one_to_one')
    monthly=[]
    for name in sorted(n for n in raw if n.startswith('raw/revenue_') and n.endswith('.html')):
        month,kind=Path(name).stem.removeprefix('revenue_').rsplit('_',1)
        monthly.append(parse_revenue(raw[name],month,int(kind)))
    monthly=pd.concat(monthly,ignore_index=True);rules=revenue_acceleration(monthly)
    matrices={}
    for lag in (45,60):
        frame=attach_revenue(base,rules,clock,lag)
        for col in ('date','flow_source_date','proxy_available_date','month_end'):frame[col]=pd.to_datetime(frame[col]).dt.strftime('%Y-%m-%d')
        matrices[str(lag)]=frame[REQUIRED].sort_values(['date','code']).reset_index(drop=True)
    # Preserve the frozen forward-reference 0050 proxy, including missing quote days.
    b=[]
    for name in sorted(n for n in raw if n.startswith('raw/benchmark_') and re.fullmatch(r'raw/benchmark_\d{4}-\d{2}\.json',n)):
        doc=json.loads(raw[name]);month=Path(name).stem.removeprefix('benchmark_')
        if doc.get('stat')!='OK' or doc.get('date')!=month.replace('-','')+'01' or '0050' not in doc.get('title',''):raise ValueError('Benchmark source month/security mismatch')
        fields=doc['fields']
        for row in doc['data']:
            r=dict(zip(fields,row));day=event_date(r['日期'])
            if day>date:continue
            b.append(dict(date=pd.Timestamp(day),symbol='0050',**{dest:number(r[src]) for dest,src in [('open','開盤價'),('high','最高價'),('low','最低價'),('close','收盤價')]}))
    benchmark=pd.DataFrame(b).sort_values('date')
    if benchmark.date.duplicated().any() or not set(benchmark.date).issubset(set(clock)):raise ValueError('Benchmark duplicate/non-market date')
    if not np.isfinite(benchmark[['open','high','low','close']]).all().all():raise ValueError('Invalid benchmark price')
    scratch=root/'benchmark_replay';scratch.mkdir(exist_ok=True)
    for kind in ('exrights','reduction','par_change','split'):
        key=f'raw/benchmark_event_{kind}.json';target=scratch/f'{kind}_{date[:4]}.json';target.write_bytes(raw[key]);meta=json.loads(raw[key+'.meta.json']);meta['fetched_at']=meta['observed_at'];atomic_json(target.with_suffix('.meta.json'),meta)
    actions=load_actions(scratch,int(date[:4]),pd.Timestamp(date));actions=actions.loc[actions.symbol.eq('0050') & actions.effective_date.ge(clock[0])]
    adjusted=adjust_prices(benchmark,actions,pd.Timestamp(date));audit=audit_events(adjusted,actions)
    if len(audit) and not audit.audit_state.eq('matched').all():raise ValueError('Benchmark event mismatch')
    entry=next_entry(raw['raw/holiday_2026.json'],date)
    summary=dict(signal_date=date,price_start=days[0],price_end=days[-1],market_days=len(days),prior_market_days=len(days)-1,quote_rows=len(q),flow_dates=days[-6:-1],revenue_months=sorted(monthly.month.unique()),benchmark_rows=len(benchmark),benchmark_missing_dates=sorted(set(days)-set(benchmark.date.dt.strftime('%Y-%m-%d'))),event_rows=len(events),unknown_event_rows=sum(e['status']!='last_close_matches' for e in events),source_last_observed_at=max(observed).isoformat(),entry_at=entry,archive_sha256=receipt['sha256'],protocol_sha256=sha256('configs/tpex_prospective_protocol.json'))
    return matrices,summary,adjusted


def generate(root):
    matrices,summary,benchmark=rebuild(root)
    for lag,frame in matrices.items():frame.to_csv(root/f'matrix_{lag}.csv',index=False,float_format='%.17g')
    benchmark.to_csv(root/'benchmark.csv',index=False,float_format='%.17g')
    atomic_json(root/'feature_summary.json',summary)


def replay(root):
    matrices,summary,benchmark=rebuild(root)
    if summary!=json.loads((root/'feature_summary.json').read_text()):raise ValueError('Feature source summary differs')
    results={};matrix_hashes={}
    protocol=frozen()
    for lag,frame in matrices.items():
        path=root/f'matrix_{lag}.csv';saved=pd.read_csv(path,dtype={'code':str,'date':str},float_precision='round_trip')
        pd.testing.assert_frame_equal(saved,frame,check_dtype=False,check_exact=False,rtol=1e-14,atol=1e-14)
        selected_protocol=json.loads(json.dumps(protocol));selected_protocol['primary']['revenue_proxy_lag_calendar_days']=int(lag)
        actual=select(frame,summary['signal_date'],selected_protocol);independent=independent_selection(frame,summary['signal_date'])
        if actual!=independent:raise ValueError('Independent selection mismatch')
        results[lag]=actual;matrix_hashes[lag]=sha256(path)
    expected=benchmark.to_csv(index=False,float_format='%.17g').encode()
    if (root/'benchmark.csv').read_bytes()!=expected:raise ValueError('Benchmark replay mismatch')
    manifest=dict(schema_version=1,source_status='raw_replay_verified',summary=summary,results=results,matrix_sha256=matrix_hashes,benchmark_sha256=sha256(root/'benchmark.csv'),verified_at=utcnow(),code_sha256={p:sha256(p) for p in ('prospective_replay.py','prospective_sources.py','prospective_selection.py','prospective_journal.py','tpex_source_pilot.py','tpex_classification_pilot.py','tpex_flow_pilot.py','acquire_tpex_revenue.py','audit_tpex_event_coverage.py','twse_history/build_history.py','twse_history/fetch_history.py')})
    atomic_json(root/'selection_manifest.json',manifest)


def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['features','replay']);p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    generate(a.root) if a.stage=='features' else replay(a.root)


def validate_live_payload(journal, payload, now):
    """Recompute evidence at sealing time; a status string/digest alone proves nothing."""
    digest=payload.get('selection_manifest_sha256','')
    if not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Invalid selection manifest digest')
    path=Path(journal)/'manifests'/f'{digest}.json'
    if sha256(path)!=digest:raise ValueError('Selection manifest hash mismatch')
    manifest=json.loads(path.read_text())
    root=Path(payload['replay_root'])
    matrices,summary,benchmark=rebuild(root)
    if manifest['source_status']!='raw_replay_verified' or manifest['summary']!=summary:
        raise ValueError('Replay evidence differs from manifest')
    verified=dt.datetime.fromisoformat(manifest['verified_at'])
    observed=dt.datetime.fromisoformat(summary['source_last_observed_at'])
    entry=dt.datetime.fromisoformat(summary['entry_at'])
    if payload.get('entry_at', summary['entry_at']) != summary['entry_at']:
        raise ValueError('Entry deadline differs from official calendar')
    if any(t.tzinfo is None for t in (verified,observed,entry)) or not observed<=verified<=now<entry:
        raise ValueError('Source/replay/entry time boundary violated')
    if payload['signal_date']!=summary['signal_date'] or payload['protocol_sha256']!=summary['protocol_sha256']:
        raise ValueError('Signal date/protocol differs from replay')
    for file,digest in manifest['code_sha256'].items():
        if sha256(file)!=digest:raise ValueError('Replay code changed after verification')
    for lag,frame in matrices.items():
        if independent_selection(frame,summary['signal_date'])!=manifest['results'][lag]:raise ValueError('Replayed selections differ')
        if sha256(root/f'matrix_{lag}.csv')!=manifest['matrix_sha256'][lag]:raise ValueError('Matrix changed after replay')
    if manifest['results']['45']['status']!='complete' or payload.get('results')!=manifest['results']:
        raise ValueError('Payload selections do not match verified manifest')
    if sha256(root/'benchmark.csv')!=manifest['benchmark_sha256']:raise ValueError('Benchmark changed after replay')
    from prospective_journal import verify
    snapshots=[verify(Path(journal)/'snapshot'/f'{ref}.json') for ref in payload['snapshot_records']]
    hashes=[]
    for snap in snapshots:
        h=snap['payload']['raw_sha256']
        if not re.fullmatch('[0-9a-f]{64}',h) or sha256(Path(journal)/'raw'/h)!=h:raise ValueError('Snapshot raw digest mismatch')
        hashes.append(h)
    if summary['archive_sha256'] not in hashes:raise ValueError('Verified archive not attached to signal')


if __name__=='__main__':main()
