"""Resumable monthly TPEx pilot, guarded by a TWSE comparison calendar, not claimed TPEx official calendar."""
import argparse,csv,datetime,gzip,hashlib,json,pathlib,subprocess,urllib.parse
from tpex_source_pilot import validate_quotes
from tpex_pool import source_types,classify

def fetch(url,path):
    tmp=path.with_suffix('.pending')
    result=subprocess.run(['curl','--max-time','25','--fail','--silent','--show-error',url,'-o',str(tmp)],capture_output=True,text=True,timeout=30)
    if result.returncode:raise RuntimeError(result.stderr[:200])
    body=tmp.read_bytes();document=json.loads(body)
    tmp.replace(path)
    path.with_suffix(path.suffix+'.meta.json').write_text(json.dumps({'url':url,'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),'fetched_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2))
    return document

def run():
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int,default=2023);parser.add_argument('--month',type=int,default=1);args=parser.parse_args()
    if not (2020<=args.year<=2026 and 1<=args.month<=12):raise ValueError('Outside frozen source-rule scope')
    pool=json.loads(pathlib.Path('configs/tpex_pool_policy.json').read_text());asof=datetime.date.fromisoformat(pool['research_asof'])
    if datetime.date(args.year,args.month,1)>asof:raise ValueError('Beyond research cutoff')
    root=pathlib.Path(f'deliverables/tpex_{args.year}');raw=root/'raw';raw.mkdir(parents=True,exist_ok=True);month=f'{args.year}{args.month:02}'
    cp=raw/f'calendar_{month}.json';cm=cp.with_suffix('.json.meta.json')
    if cp.exists() and cm.exists():
        body=cp.read_bytes()
        if hashlib.sha256(body).hexdigest()!=json.loads(cm.read_text())['sha256']:raise ValueError('Calendar cache hash mismatch')
        calendar=json.loads(body)
    else:calendar=fetch('https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date='+month+'01',cp)
    if calendar.get('stat')!='OK' or not calendar.get('data'):raise ValueError('Calendar unavailable')
    days=[]
    for r in calendar['data']:
        y,m,d=map(int,r[0].split('/'));date=datetime.date(y+1911,m,d)
        if date<=asof:days.append(date)
    known,exact=source_types(pathlib.Path('deliverables/tpex_pilot'));rows=[];summary=[]
    for date in days:
        f=raw/f'quotes_{date:%Y%m%d}.json';u='https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?'+urllib.parse.urlencode({'date':date.strftime('%Y/%m/%d'),'type':'EW','response':'json'})
        meta=f.with_suffix(f.suffix+'.meta.json')
        if f.exists() and meta.exists():
            body=f.read_bytes();assert hashlib.sha256(body).hexdigest()==json.loads(meta.read_text())['sha256'];doc=json.loads(body)
        else:doc=fetch(u,f)
        checked=validate_quotes(doc,date.isoformat());table=doc['tables'][0];fields=[x.strip() for x in table['fields']];count={'confirmed':0,'candidate':0,'unknown':0,'nonordinary':0}
        for r in table['data']:
            code=r[0];tier,cfi=classify(code,known,exact);primary=tier in pool['primary_includes'];sensitivity=tier=='confirmed_ordinary'
            count['confirmed' if sensitivity else 'candidate' if primary else 'nonordinary' if tier=='confirmed_nonordinary' else 'unknown']+=1
            rows.append({'date':date.isoformat(),'code':code,'historical_name':r[1],'type_evidence':tier,'cfi':cfi,'primary_pool':primary,'confirmed_subset':sensitivity,'open':r[fields.index('開盤')],'high':r[fields.index('最高')],'low':r[fields.index('最低')],'close':r[fields.index('收盤')],'volume_shares':r[fields.index('成交股數')],'amount_twd':r[fields.index('成交金額(元)')]})
        checked.update(count);summary.append(checked);print(date,len(table['data']),count,flush=True)
    out=root/f'quotes_with_type_{month}.csv.gz'
    with gzip.open(out,'wt',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    status={'month':month,'comparison_calendar_days':len(days),'downloaded_validated_days':len(summary),'all_security_rows':len(rows),'primary_rows':sum(r['primary_pool'] for r in rows),'confirmed_subset_rows':sum(r['confirmed_subset'] for r in rows),'policy_sha256':hashlib.sha256(pathlib.Path('configs/tpex_pool_policy.json').read_bytes()).hexdigest(),'output_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'limitations':['TWSE comparison calendar; TPEx independent official calendar not yet verified','historical quote-present pool; completely absent/suspended securities master pending','raw unadjusted OHLC; not ready for model labels'],'daily':summary}
    (root/f'summary_{month}.json').write_text(json.dumps(status,ensure_ascii=False,indent=2));print('complete',len(days),len(rows),flush=True)
if __name__=='__main__':run()
