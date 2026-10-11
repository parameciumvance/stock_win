"""Reproducible full-year source pipeline; stop on errors, no model fitting."""
import argparse,concurrent.futures,hashlib,json,pathlib,subprocess,sys
from acquire_tpex_month import fetch

def main():
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);a=p.parse_args()
    if a.year not in range(2020,2026):raise ValueError('Full completed years 2020–2025 only; partial 2026 needs separate cutoff audit')
    root=pathlib.Path(f'deliverables/tpex_{a.year}');root.mkdir(exist_ok=True)
    names=['isin.raw','isin_listed.raw','unknown_single_query.html']
    inputs={n:hashlib.sha256((pathlib.Path('deliverables/tpex_pilot/classification')/n).read_bytes()).hexdigest() for n in names}
    pinned=root/'type_input_hashes.json'
    if pinned.exists():
        if json.loads(pinned.read_text())['sources']!=inputs:raise ValueError('Type evidence drift')
    else:pinned.write_text(json.dumps({'sources':inputs},indent=2)+'\n')
    def month(m):
        with (root/f'acquire_{m:02}.log').open('a') as log:
            for attempt in range(2):
                r=subprocess.run([sys.executable,'-u','acquire_tpex_month.py','--year',str(a.year),'--month',str(m)],stdout=log,stderr=subprocess.STDOUT)
                if r.returncode==0:print('complete month',m,flush=True);return
        raise RuntimeError(f'Month {m} failed twice; inspect acquire_{m:02}.log; source failure is not a holiday')
    with concurrent.futures.ThreadPoolExecutor(2) as ex:
        for start in range(1,13,2):list(ex.map(month,[start,start+1]))
    for name,action in [('excal_history','exDailyQ'),('reduction_history','revivt'),('change_history','pvChgRslt')]:
        dest=root/'raw'/(name+'.json');meta=dest.with_suffix('.json.meta.json')
        if dest.exists() and meta.exists():
            body=dest.read_bytes()
            if hashlib.sha256(body).hexdigest()!=json.loads(meta.read_text())['sha256']:raise ValueError('Company-action cache hash mismatch')
            doc=json.loads(body)
        else:doc=fetch(f'https://www.tpex.org.tw/www/zh-tw/bulletin/{action}?startDate={a.year}/01/01&endDate={a.year}/12/31&response=json',dest)
        if doc.get('stat')!='ok' or doc.get('date')!=f'{a.year}0101~{a.year}1231':raise ValueError('Company-action source unavailable or wrong range')
    subprocess.run([sys.executable,'-u','audit_tpex_calendar.py','--year',str(a.year)],check=True)
    subprocess.run([sys.executable,'-u','finalize_tpex_year.py','--year',str(a.year)],check=True)
    print('Local checkpoint complete; save and verify a round trip before declaring durable completion',flush=True)

if __name__=='__main__':main()
