"""Different-route/source adjudication, without altering frozen conflicting snapshots."""
import argparse
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from ipo_account import compact_html
from ipo_screen import parse_year,reconcile_csv,roc,terms,FIELDS
from research_runtime import atomic_json,exclusive_lock,sha256
from source_checkpoint import package_sources,readback
from tender_preflight import verified_records

ROOT=Path('inputs/ipo_adjudication_20261020')
OUT=Path('deliverables/ipo_adjudication_20261020')
POLICY=Path('configs/ipo_adjudication_protocol_20261020.json')


def policy():
    p=json.loads(POLICY.read_text())
    if sha256(POLICY)!=json.loads((OUT/'protocol_freeze.json').read_text())['protocol_sha256']:raise ValueError('Adjudication protocol drift')
    for file,digest in p['request_configs_sha256'].items():
        if sha256(Path(file))!=digest:raise ValueError('Request configuration drift')
    for file,digest in p['prior_checkpoints'].items():
        if sha256(Path(file))!=digest:raise ValueError('Prior checkpoint drift')
        for name,h in json.loads(Path(file).read_text())['files'].items():
            if sha256(Path(name))!=h:raise ValueError('Prior output drift: '+name)
    return p


def package():
    p=policy();entries={'protocol.json':POLICY};count=0
    for file in p['request_configs_sha256']:
        cfg=json.loads(Path(file).read_text());root=Path(cfg['output_directory']);count+=len(cfg['requests'])
        results=json.loads((root/'results.json').read_text())
        if results['config_sha256']!=sha256(Path(file)):raise ValueError('Acquisition request drift')
        verified_records(cfg,results,lambda n:(root/n).read_bytes())
        entries[Path(file).name]=Path(file)
        entries.update({root.name+'/'+f.name:f for f in root.iterdir() if f.is_file()})
    if count>p['max_requests']:raise ValueError('Request bound exceeded')
    with exclusive_lock(ROOT/'acquisition.lock'):package_sources(ROOT,OUT,'sources',entries)


def annual_control(body):
    if not body.startswith(b'%PDF-'):return dict(verified=False,error='Not a PDF')
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(body));matches=[];numeric_candidates=[]
    for i,page in enumerate(reader.pages):
        text=''.join((page.extract_text() or '').split())
        if '中華資安國際' in text:
            start=text.index('中華資安國際');matches.append(dict(page=i+1,context=text[max(0,start-30):start+240]))
        if '148,988,000' in text and '114/09/02' in text:
            start=text.index('148,988,000');numeric_candidates.append(dict(page=i+1,context=text[max(0,start-50):start+70]))
    exact=any(re.search(r'中華資安國際初次上市元大證券626238148,988,000114/09/020\.25',m['context']) for m in matches)
    return dict(verified=exact,pages=len(reader.pages),matches=matches,numeric_candidates=numeric_candidates,
        scope='Selected7765annualtable row only; roundedodds0.25%,626lots,price238. Numeric-only candidates without readable issuer identity are not verified. Not qualified application count or historical publication proof')


def audit():
    p=policy();pkg,transfer=readback(OUT,'sources')
    with zipfile.ZipFile(pkg['retrieved']) as z:data={name:z.read(name) for name in z.namelist()}
    if data['protocol.json']!=POLICY.read_bytes():raise ValueError('Archived protocol drift')
    observations=[]
    for file in p['request_configs_sha256']:
        cfg=json.loads(Path(file).read_text());prefix=Path(cfg['output_directory']).name+'/'
        if data[Path(file).name]!=Path(file).read_bytes():raise ValueError('Archived requests drift')
        result=json.loads(data[prefix+'results.json'])
        if result['config_sha256']!=sha256(Path(file)):raise ValueError('Archived request metadata drift')
        observations+=verified_records(cfg,result,lambda n:data[prefix+n])
    ok=lambda name:any(r['request']['filename']==name and r.get('http_status')==200 and r.get('exit_code')==0 for r in observations)
    errors=[];rows=None;differences_new=[]
    if all(ok(n) for n in ['2025_rwd.json','2025_rwd.csv']):
        try:
            from ipo_source_consistency import csv_rows,differences
            rows=parse_year(data['raw_native/2025_rwd.json'],2025)
            differences_new=differences(rows,csv_rows(data['raw_native/2025_rwd.csv']))
            reconcile_csv(data['raw_native/2025_rwd.csv'],rows)
        except (ValueError,UnicodeError) as error:errors.append(type(error).__name__+': '+str(error));rows=None
    else:errors.append('Native route transport failed; no fallback or insecure TLS')
    fubon=dict(verified=False)
    if ok('6936_fubon.html'):
        text=compact_html(data['raw_controls/6936_fubon.html'])
        fubon=dict(verified='6936' in text and '承銷價每股28.01元' in text,scope='Issuer underwriter group2025listing news; corroborates6936finaloffer28.01only')
    annual=annual_control(data['raw_controls/tsa_2025.pdf']) if ok('tsa_2025.pdf') else dict(verified=False,error='Annual report transport failed')
    controls=False
    if rows is not None and fubon['verified'] and annual['verified']:
        bysymbol={r[3]:r for r in rows}
        a=bysymbol.get('6936');b=bysymbol.get('7765')
        controls=bool(a and b and Decimal(a[10].replace(',',''))==Decimal('28.01') and Decimal(b[10].replace(',',''))==238 and Decimal(b[8].replace(',',''))==626000 and Decimal(b[16])==Decimal('0.25'))
    passed=rows is not None and controls
    if not controls:errors.append('Both independent controls and corresponding full-table fields must corroborate')
    atomic_json(OUT/'source_receipt.json',dict(status='source_adjudication_passed' if passed else 'source_adjudication_unresolved',archive_sha256=pkg['sha256'],manifest_files=pkg['manifest_files'],backup=transfer,
        sha_crc_manifest_verified=True,full_new_json_csv_agreement=rows is not None,rows=len(rows) if rows else None,independent_controls_passed=controls,fubon_control=fubon,annual_control=annual,
        source_gate_passed=passed,errors=errors,historical_pit_verified=False,root_cause='Unidentified; client and route both differ, so this experiment does not isolate the cause',
        native_representation_differences=differences_new,
        observations=[{k:r.get(k) for k in ['request','http_status','exit_code','size_bytes','sha256','request_started_at','observed_at','error']}|dict(stderr=r.get('stderr') if r.get('exit_code')!=0 else '') for r in observations]))
    if not passed:return
    # Keep the new current historical snapshot separate. No repair to old frozen files.
    cases=[dict(symbol=r[3],name=r[2],draw_date=roc(r[1]),application_start=roc(r[5]),application_end=roc(r[6]),listing_date=roc(r[11]),reported_fields=dict(zip(FIELDS,r))) for r in rows if r[4]=='初上市']
    old=json.loads(Path('configs/ipo_replication_protocol_20261020.json').read_text())
    compatibility=[]
    for case in cases:
        t=terms(case,old);compatibility.append(dict(symbol=case['symbol'],name=case['name'],terms=t))
    atomic_json(OUT/'cases.json',cases)
    atomic_json(OUT/'term_compatibility.json',dict(events=len(cases),cases=compatibility,affordable_term_gaps=[r['symbol'] for r in compatibility if r['terms']['individually_affordable'] and r['terms']['issues']],
        source_gate_passed=True,market_endpoints_inspected=False,current_rule_parameters_changed=False))
    from ipo_source_consistency import csv_rows,html_rows,differences
    with zipfile.ZipFile('inputs/ipo_replication_20261020/sources.retrieved.zip') as z:
        original=[('initial_json',parse_year(z.read('raw/2025.json'),2025)),('initial_csv',csv_rows(z.read('raw/2025.csv')))]
    with zipfile.ZipFile('inputs/ipo_replication_20261020/recovery.retrieved.zip') as z:
        original += [('retry_json',parse_year(z.read('raw/2025_retry.json'),2025)),('retry_csv',csv_rows(z.read('raw/2025_retry.csv'))),('html_control',html_rows(z.read('raw/2025_control.html'),2025))]
    atomic_json(OUT/'old_snapshot_comparison.json',dict(new_snapshot_body_sha256=hashlib.sha256(data['raw_native/2025_rwd.json']).hexdigest(),
        comparison=[dict(old=name,differences=differences(before,rows)) for name,before in original],no_old_files_replaced=True,no_field_stitching=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['package','audit']);globals()[parser.parse_args().stage]()
