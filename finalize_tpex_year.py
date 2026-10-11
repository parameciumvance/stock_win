"""Fail-closed annual quote/type checkpoint; does not construct adjusted prices or labels."""
import argparse,csv,datetime,gzip,hashlib,json,pathlib,zipfile
from tpex_source_pilot import validate_quotes
from tpex_pool import source_types,classify

def main():
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,default=2023);a=p.parse_args();root=pathlib.Path(f'deliverables/tpex_{a.year}');raw=root/'raw'
    cal=json.loads((root/'calendar_audit.json').read_text());expected=[d for m in cal['months'] for d in m['dates']]
    if len(expected)!=len(set(expected)):raise ValueError('Duplicate calendar day')
    summaries=[];count=primary=subset=0;codes=set();daily=[];normalized={}
    type_hashes=json.loads((root/'type_input_hashes.json').read_text())['sources']
    for name,h in type_hashes.items():
        if hashlib.sha256((pathlib.Path('deliverables/tpex_pilot/classification')/name).read_bytes()).hexdigest()!=h:raise ValueError('Type evidence changed during acquisition')
    known,exact=source_types(pathlib.Path('deliverables/tpex_pilot'))
    out=root/f'quotes_with_type_{a.year}.csv.gz';pending=out.with_suffix('.pending.gz');seen=set();rawkeys=set();fields=None
    with gzip.open(pending,'wt',newline='') as dst:
        writer=None
        for m in range(1,13):
            month=f'{a.year}{m:02}';summary=json.loads((root/f'summary_{month}.json').read_text());source=root/f'quotes_with_type_{month}.csv.gz'
            if hashlib.sha256(source.read_bytes()).hexdigest()!=summary['output_sha256']:raise ValueError('Monthly CSV hash mismatch')
            if summary['policy_sha256']!=hashlib.sha256(pathlib.Path('configs/tpex_pool_policy.json').read_bytes()).hexdigest():raise ValueError('Policy drift')
            summaries.append(summary)
            with gzip.open(source,'rt',newline='') as f:
                reader=csv.DictReader(f)
                if fields is None:fields=reader.fieldnames;writer=csv.DictWriter(dst,fieldnames=fields);writer.writeheader()
                if reader.fieldnames!=fields:raise ValueError('Monthly schema drift')
                for row in reader:
                    key=(row['date'],row['code'])
                    if key in seen:raise ValueError('Duplicate date/security')
                    seen.add(key);normalized[key]=row;codes.add(row['code']);count+=1
                    primary+=row['primary_pool']=='True';subset+=row['confirmed_subset']=='True'
                    if row['type_evidence']=='ordinary_stock_rule_candidate' and row['cfi']:raise ValueError('Fabricated candidate CFI')
                    if row['confirmed_subset']=='True' and row['primary_pool']!='True':raise ValueError('Subset violates policy')
                    writer.writerow(row)
            dates=[r['requested_date'] for r in summary['daily']]
            if dates!=cal['months'][m-1]['dates']:raise ValueError('Calendar/quote coverage differs')
            for date in dates:
                path=raw/('quotes_'+date.replace('-','')+'.json');body=path.read_bytes();meta=json.loads(path.with_suffix('.json.meta.json').read_text())
                if hashlib.sha256(body).hexdigest()!=meta['sha256']:raise ValueError('Raw response hash mismatch')
                document=json.loads(body);checked=validate_quotes(document,date);daily.append(checked)
                table=document['tables'][0];names=[x.strip() for x in table['fields']]
                for r in table['data']:
                    rawkeys.add((date,r[0]));result=normalized[(date,r[0])];tier,cfi=classify(r[0],known,exact)
                    if (result['primary_pool']=='True')!=(tier in ['confirmed_ordinary','ordinary_stock_rule_candidate']) or (result['confirmed_subset']=='True')!=(tier=='confirmed_ordinary'):raise ValueError('Pool boolean differs from fixed policy')
                    if result['type_evidence']!=tier or result['cfi']!=cfi:raise ValueError('Normalized type differs from source evidence')
                    for dest,src in [('open','開盤'),('high','最高'),('low','最低'),('close','收盤'),('volume_shares','成交股數'),('amount_twd','成交金額(元)')]:
                        if result[dest]!=r[names.index(src)]:raise ValueError('Normalized quote differs from raw response')
            cal['months'][m-1]['quote_month_complete']=True
            cp=json.loads((raw/f'calendar_{month}.json').read_text());comparison=[]
            for r in cp['data']:
                yy,mm,dd=map(int,r[0].split('/'));comparison.append(datetime.date(yy+1911,mm,dd).isoformat())
            if comparison!=dates:raise ValueError('TWSE/TPEx calendar mismatch')
            cal['months'][m-1]['twse_comparison_verified']=True
    if [r['requested_date'] for r in daily]!=expected:raise ValueError('Annual date coverage mismatch')
    if rawkeys!=seen or count!=sum(r['rows'] for r in daily):raise ValueError('Annual raw/normalized keys differ')
    pending.replace(out);(root/'calendar_audit.json').write_text(json.dumps(cal,indent=2))
    status={'year':a.year,'verified_market_days':len(expected),'all_security_rows':count,'unique_securities':len(codes),'primary_pool_rows':primary,'confirmed_subset_rows':subset,'ordinary_rule_candidate_rows':primary-subset,'output_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'status':'annual_raw_quotes_type_policy_and_independent_calendar_verified','not_completed':['adjusted prices','full suspended-security membership master','company-action reference audit','features/model/backtest'],'daily':daily}
    (root/'annual_verification.json').write_text(json.dumps(status,ensure_ascii=False,indent=2))
    files=[x for x in raw.rglob('*') if x.is_file() and not x.name.endswith('.pending')]+list(root.glob('summary_*.json'))+list(root.glob('quotes_with_type_*.csv.gz'))+[root/'calendar_audit.json',root/'annual_verification.json',root/'type_input_hashes.json']+list(root.glob('calendar_check_*.json'))
    manifest={str(x.relative_to(root)):hashlib.sha256(x.read_bytes()).hexdigest() for x in files};mp=root/'SHA256MANIFEST_YEAR.json';mp.write_text(json.dumps(manifest,indent=2))
    archive=root/f'tpex_raw_type_{a.year}_checkpoint.zip';temp=archive.with_suffix('.pending.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for x in files+[mp]:z.write(x,str(x.relative_to(root)))
    with zipfile.ZipFile(temp) as z:
        if z.testzip() is not None:raise ValueError('ZIP CRC failure')
        for n,h in manifest.items():
            if hashlib.sha256(z.read(n)).hexdigest()!=h:raise ValueError('ZIP member hash mismatch')
    temp.replace(archive);checkpoint={'archive':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'manifest_files':len(manifest),'zip_members':len(manifest)+1}
    (root/'checkpoint.json').write_text(json.dumps(checkpoint,indent=2));print(json.dumps({k:v for k,v in status.items() if k!='daily'}));print(json.dumps(checkpoint))
if __name__=='__main__':main()
