"""Audit preserved IPO representations; fail closed on conflicts, never vote or stitch fields."""
import csv
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import zipfile

from ipo_screen import FIELDS, parse_year, reconcile_csv
from research_runtime import atomic_json, sha256
from source_checkpoint import readback
from tender_preflight import verified_records

ROOT=Path('inputs/ipo_replication_20261020')
OUT=Path('deliverables/ipo_replication_20261020')


class Table(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ['td','th']:self.cell=[]
    def handle_data(self,value):
        if self.cell is not None:self.cell.append(value)
    def handle_endtag(self,tag):
        if tag in ['td','th'] and self.cell is not None:
            if self.row is not None:self.row.append(''.join(self.cell).strip())
            self.cell=None
        if tag=='tr' and self.row is not None:
            self.rows.append(self.row);self.row=None


def html_rows(body,year):
    parser=Table();parser.feed(body.decode('utf-8'))
    if sum(r==FIELDS for r in parser.rows)!=1:raise ValueError('HTML field header mismatch')
    rows=[r for r in parser.rows if r and r[0].isdigit()]
    # Reuse strict year, sequence, width and schema checks; do not strip source cell content beyond HTML layout.
    return parse_year(json.dumps(dict(stat='OK',date=str(year),fields=FIELDS,total=len(rows),data=rows)),year)


def csv_rows(body):
    rows=list(csv.reader(io.StringIO(body.decode('cp950'))))
    if sum([s.strip() for s in r[:18]]==FIELDS for r in rows)!=1:raise ValueError('CSV field header mismatch')
    data=[r for r in rows if r and r[0].isdigit()]
    if any(len(r)!=19 or r[-1]!='' for r in data):raise ValueError('CSV row width mismatch')
    return [r[:18] for r in data]


def differences(left,right):
    if len(left)!=len(right):raise ValueError('Representation row counts differ')
    result=[]
    for a,b in zip(left,right):
        if len(a)!=len(FIELDS) or len(b)!=len(FIELDS) or a[:5]!=b[:5]:raise ValueError('Representation identity/schema drift')
        if a!=b:
            result.append(dict(sequence=a[0],symbol=a[3],category=a[4],fields=[dict(field=field,left=x,right=y) for field,x,y in zip(FIELDS,a,b) if x!=y]))
    return result


def require_consistency(versions):
    if len(versions)!=3 or any(v!=versions[0] for v in versions[1:]):
        raise ValueError('Three representations conflict; no majority vote or field stitching permitted')
    return versions[0]


def archive(tag,requests,protocol,protocol_member):
    pkg,transfer=readback(OUT,tag)
    with zipfile.ZipFile(pkg['retrieved']) as z:data={name:z.read(name) for name in z.namelist()}
    if data['requests.json']!=requests.read_bytes() or data[protocol_member]!=protocol.read_bytes():raise ValueError('Archived frozen request/protocol drift')
    results=json.loads(data['raw/results.json']);cfg=json.loads(requests.read_text())
    if results['config_sha256']!=sha256(requests):raise ValueError('Archived source config differs')
    records=verified_records(cfg,results,lambda name:data['raw/'+name])
    if any(r.get('http_status')!=200 or r.get('exit_code')!=0 for r in records):raise ValueError('Transport failure is not a valid table')
    return data,dict(archive_sha256=pkg['sha256'],manifest_files=pkg['manifest_files'],backup=transfer,sha_crc_manifest_verified=True,
        observations=[{k:r.get(k) for k in ['request','http_status','exit_code','size_bytes','sha256','request_started_at','observed_at']} for r in records])


def audit():
    protocol=Path('configs/ipo_replication_recovery_protocol_20261020.json');p=json.loads(protocol.read_text())
    if sha256(protocol)!=json.loads((OUT/'source_recovery_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Recovery protocol freeze differs')
    if sha256(OUT/'sources_package.json')!=p['original_source_package_sha256']:raise ValueError('Original source package receipt drift')
    req=Path('configs/ipo_replication_recovery_sources.json')
    if sha256(req)!=p['source_requests_sha256']:raise ValueError('Recovery requests drift')
    original,receipt0=archive('sources',Path('configs/ipo_replication_sources.json'),Path('configs/ipo_replication_protocol_20261020.json'),'protocol.json')
    recovery,receipt1=archive('recovery',req,protocol,'recovery_protocol.json')
    initial_json=parse_year(original['raw/2025.json'],2025);initial_csv=csv_rows(original['raw/2025.csv'])
    retry_json=parse_year(recovery['raw/2025_retry.json'],2025);retry_csv=csv_rows(recovery['raw/2025_retry.csv']);control=html_rows(recovery['raw/2025_control.html'],2025)
    pairs=[('initial_json_vs_initial_csv',initial_json,initial_csv),('initial_json_vs_retry_json',initial_json,retry_json),('retry_json_vs_retry_csv',retry_json,retry_csv),('retry_json_vs_html',retry_json,control),('initial_json_vs_html',initial_json,control)]
    comparisons=[]
    for name,a,b in pairs:
        diff=differences(a,b);comparisons.append(dict(name=name,rows_differ=len(diff),cohort_rows_differ=sum(r['category']=='初上市' for r in diff),differences=diff))
    try:
        require_consistency([retry_json,retry_csv,control]);recovered=True
    except ValueError:recovered=False
    atomic_json(OUT/'source_consistency.json',dict(status='consistent_recovered_snapshot' if recovered else 'blocked_source_representations_disagree',
        audit_completed=True,usable_for_research=recovered,all_representations_rows=[len(v) for v in [initial_json,initial_csv,retry_json,retry_csv,control]],
        initial_cohort_events=sum(r[4]=='初上市' for r in initial_json),comparisons=comparisons,no_majority_vote=True,no_field_stitching=True,no_market_endpoints_inspected=True,
        source_cause='Unknown; observed HTTP200, curl0 and differing preserved content. No inference of website or transport root cause.',historical_pit_verified=False))
    atomic_json(OUT/'source_receipt.json',dict(status='archival_readback_passed_semantic_consistency_failed' if not recovered else 'archival_and_consistency_passed',
        sha_crc_manifest_verified=True,packages=[receipt0,receipt1],total_requests=5,semantic_consistency_passed=recovered))


if __name__=='__main__':audit()
