"""Verified free TWSE credit balances, retaining unavailable observations.

The next-business-day O/X annotations are announced in the daily report;
they are not a record of that day's executed financing transactions.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

import pandas as pd

from twse_history.institutional import market_days_from_cache

FIELDS=['代號','名稱','買進','賣出','現金償還','前日餘額','今日餘額','次一營業日限額',
        '買進','賣出','現券償還','前日餘額','今日餘額','次一營業日限額','資券互抵','註記']
COLUMNS=['finance_buy','finance_sell','finance_cash_repay','finance_prev','finance_today','finance_limit',
         'short_buy','short_sell','short_stock_repay','short_prev','short_today','short_limit','offset']


def parse(raw, day):
    day=pd.Timestamp(day).date().isoformat()
    x=json.loads(raw)
    compact=day.replace('-','')
    if x.get('stat')!='OK' or x.get('date')!=compact:
        raise ValueError('Wrong credit source date/status')
    tables=[t for t in x.get('tables',[]) if t.get('fields')==FIELDS]
    if len(tables)!=1 or not tables[0].get('data'):
        raise ValueError('Unexpected credit schema')
    table=tables[0]
    if not any('次一營業日' in n for n in table.get('notes',[])):
        raise ValueError('Missing next-business-day annotation semantics')
    rows=[]
    for r in table['data']:
        if len(r)!=16:raise ValueError('Wrong credit row width')
        symbol=str(r[0]).strip()
        if not re.fullmatch(r'[0-9A-Z]{4,10}',symbol):raise ValueError('Unexpected security code')
        numbers=[int(str(v).replace(',','').strip()) for v in r[2:15]]
        if min(numbers)<0:raise ValueError('Negative credit transaction/balance')
        v=dict(zip(COLUMNS,numbers))
        if v['finance_today']!=v['finance_prev']+v['finance_buy']-v['finance_sell']-v['finance_cash_repay']:
            raise ValueError(f'Finance balance identity mismatch: {day}/{symbol}')
        if v['short_today']!=v['short_prev']+v['short_sell']-v['short_buy']-v['short_stock_repay']:
            raise ValueError(f'Short balance identity mismatch: {day}/{symbol}')
        flags=str(r[15]).strip()
        if set(flags)-set('OX@%!'):raise ValueError('Unknown credit annotation')
        rows.append(dict(date=day,symbol=symbol,name=r[1],**v,next_business_day_flags=flags))
    f=pd.DataFrame(rows)
    if f.symbol.duplicated().any():raise ValueError('Duplicate credit symbol')
    return f


def cached(root,day,fetch=False):
    compact=day.replace('-','');url=f'https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date={compact}&selectType=ALL'
    path=root/f'margin_{compact}.json';mp=root/f'margin_{compact}.meta.json'
    if path.exists()!=mp.exists():raise ValueError('Incomplete credit cache pair')
    if not path.exists():
        if not fetch:raise FileNotFoundError(path)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url,timeout=15) as response:
                    raw=response.read();meta=dict(source_url=url,final_url=response.url,http_status=response.status,
                       sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),fetched_at=datetime.now(timezone.utc).isoformat())
                if meta['http_status']!=200 or meta['final_url']!=url:raise ValueError('Redirected/error credit source')
                parse(raw,day)
                root.mkdir(parents=True,exist_ok=True)
                path.write_bytes(raw);mp.write_text(json.dumps(meta,indent=2)+'\n')
                break
            except Exception:
                if attempt==2:raise
                time.sleep(2)
        time.sleep(.5)
    raw=path.read_bytes();meta=json.loads(mp.read_text())
    if meta['sha256']!=hashlib.sha256(raw).hexdigest() or meta['source_url']!=url or meta['final_url']!=url or meta['http_status']!=200:
        raise ValueError('Unverified credit cache')
    return parse(raw,day),meta


def acquire(year,asof=None,fetch=False):
    days=[str(d) for d in market_days_from_cache(Path('twse_history/raw'),year,asof)]
    root=Path(f'inputs/margin/raw_{year}')
    frames=[];meta=[]
    pool=ThreadPoolExecutor(max_workers=2)
    try:
        for i,(f,m) in enumerate(pool.map(lambda d:cached(root,d,fetch),days),1):
            frames.append(f);meta.append(dict(m,date=days[i-1],rows=len(f)))
            if i%5==0:print(f'year={year} verified={i}/{len(days)} date={days[i-1]}',flush=True)
    except BaseException:
        # Do not wait for a whole queued year after the first failed source.
        pool.shutdown(wait=False,cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
    full=pd.concat(frames,ignore_index=True)
    output=Path('inputs/margin');output.mkdir(exist_ok=True,parents=True)
    path=output/f'margin_twse_{year}.csv.gz'
    full.to_csv(path,index=False,compression={'method':'gzip','mtime':0})
    result=dict(year=year,asof=asof,days=len(days),raw_security_rows=len(full),
                normalized_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),sources=meta,
                status='historical_daily_snapshot_not_verified_original_vintage')
    p=Path(f'deliverables/margin');p.mkdir(exist_ok=True,parents=True)
    (p/f'acquisition_{year}.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='sources'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--year',type=int,required=True);p.add_argument('--asof');p.add_argument('--fetch',action='store_true')
    a=p.parse_args();acquire(a.year,a.asof,a.fetch)
