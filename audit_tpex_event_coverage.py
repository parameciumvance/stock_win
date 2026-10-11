"""Match official 2023 events to raw quotes; never manufacture adjustment factors."""
import argparse,bisect,csv,datetime,gzip,hashlib,json,pathlib

def event_date(value):
    s=str(value).replace('/','')
    return datetime.date(int(s[:3])+1911,int(s[3:5]),int(s[5:7])).isoformat()

def number(s):
    try:return float(str(s).replace(',',''))
    except ValueError:return None

def run(year=2023):
    root=pathlib.Path(f'deliverables/tpex_{year}')
    with gzip.open(root/f'quotes_with_type_{year}.csv.gz','rt') as f:rows=list(csv.DictReader(f))
    quotes={(r['date'],r['code']):r for r in rows}
    days=sorted({r['date'] for r in rows});records=[]
    catalog={r['name']:r for r in json.loads(pathlib.Path('deliverables/tpex_pilot/history_probe.json').read_text())} if year==2023 else None
    for filename,kind in [('excal_history.json','ex_right_dividend'),('reduction_history.json','capital_reduction'),('change_history.json','face_value_change')]:
        path=(pathlib.Path('deliverables/tpex_pilot') if year==2023 else root/'raw')/filename
        body=path.read_bytes()
        meta=catalog[pathlib.Path(filename).stem] if catalog else json.loads(path.with_suffix('.json.meta.json').read_text())
        if hashlib.sha256(body).hexdigest()!=meta['sha256']:raise ValueError('Event source hash mismatch')
        doc=json.loads(body)
        if doc.get('stat')!='ok' or doc.get('date')!=f'{year}0101~{year}1231':raise ValueError('Wrong event source range')
        for table in doc.get('tables',[]):
            for e in table['data']:
                date=event_date(e[0]);code=e[1]
                if not date.startswith(f'{year}-'):raise ValueError('Unexpected source year')
                idx=bisect.bisect_left(days,date);before=None
                for d in reversed(days[:idx]):
                    q=quotes.get((d,code))
                    if q and number(q['close']) is not None:before=q;break
                on=quotes.get((date,code));last=number(e[3]);ref=number(e[4])
                status='last_close_matches' if before and number(before['close'])==last else ('missing_prior_quote' if before is None else 'last_close_mismatch')
                if date not in days:status='event_date_outside_market_calendar'
                records.append({'event_date':date,'code':code,'kind':kind,'source_file':filename,'official_last_close':last,'official_reference':ref,'prior_quote_date':before['date'] if before else None,'prior_quote_close':number(before['close']) if before else None,'on_event_close':number(on['close']) if on else None,'primary_pool':on['primary_pool']=='True' if on else None,'status':status})
    import collections
    summary={'year':year,'events':len(records),'by_kind':dict(collections.Counter(r['kind'] for r in records)),'by_status':dict(collections.Counter(r['status'] for r in records)),'scope':'all source events including nonordinary securities; quote bridge only','not_completed':['reference formula and rounding verification','cash ledger','adjusted price construction']}
    (root/'event_coverage.json').write_text(json.dumps({'summary':summary,'records':records},indent=2))
    (root/'event_coverage_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,default=2023);run(p.parse_args().year)
