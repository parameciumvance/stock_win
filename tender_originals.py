"""Follow frozen public-tender references; never execute page scripts or query prices."""
import argparse
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urljoin
import zipfile
from io import BytesIO

from research_runtime import atomic_json, exclusive_lock, sha256, utcnow
from source_checkpoint import package_sources, readback
from tender_preflight import verified_records, table_text

ROOT = Path('inputs/tender_originals_20261019')
OUT = Path('deliverables/tender_originals_20261019')
PARENT = Path('deliverables/tender_preflight_20261019')
POLICY = Path('configs/tender_originals_protocol_20261019.json')


class BidderReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = self.table_number = 0
        self.rows = []
        self.row = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'table':
            self.depth += 1
            if self.depth == 1:
                self.table_number += 1
        if self.depth == 1 and self.table_number == 1:
            if tag == 'tr':
                self.row = dict(links=[], actions=[])
                self.rows.append(self.row)
            elif self.row is not None:
                if tag == 'a' and 'href' in a:
                    self.row['links'].append(a['href'])
                if tag == 'input' and 'onclick' in a:
                    self.row['actions'].append(a['onclick'])

    def handle_endtag(self, tag):
        if tag == 'table':
            self.depth -= 1
        if tag == 'tr':
            self.row = None


def request_for_pointer(row, document, symbol, index):
    filename = f'{symbol}_{index:02d}.html'
    if document['filename']:
        if len(row['links']) != 1 or row['actions']:
            raise ValueError('Ambiguous PDF reference')
        url = row['links'][0]
        parts = urlsplit(url)
        q = parse_qs(parts.query)
        if parts.scheme != 'https' or parts.netloc != 'doc.twse.com.tw' or parts.path != '/server-java/t57sb01' or q.get('filename') != [document['filename']] or q.get('kind') != ['B'] or q.get('step') != ['9']:
            raise ValueError('Unexpected document gateway')
        return dict(filename=filename, url=url)
    if row['links'] or len(row['actions']) != 1:
        raise ValueError('Ambiguous announcement reference')
    pairs = re.findall(r'document\.form2\.([A-Z_0-9a-z]+)\.value="([0-9]+)"', row['actions'][0])
    fields = dict(pairs)
    if len(pairs) != 5 or set(fields) != {'step','COMPANY_ID2','SEQ_NO','DATE','TYPE'} or fields['step'] != '2' or fields['COMPANY_ID2'] != symbol or not re.fullmatch(r'\d{8}', fields['DATE']):
        raise ValueError('Unexpected announcement form fields')
    return dict(filename=filename, url='https://mopsov.twse.com.tw/mops/web/ajax_t162sb01', method='POST',
                data=urlencode(dict(step='2',off='1',firstin='1',COMPANY_ID2=fields['COMPANY_ID2'],TYPE=fields['TYPE'],DATE=fields['DATE'],SEQ_NO=fields['SEQ_NO'])))


def parent_verified():
    c = json.loads((PARENT / 'checkpoint.json').read_text())
    for name, digest in c['files'].items():
        if sha256(name) != digest:
            raise ValueError('Frozen parent checkpoint drift: ' + name)
    package, _ = readback(PARENT, 'cohort')
    return package


def freeze():
    if POLICY.exists() or (OUT / 'protocol_freeze.json').exists():
        raise ValueError('Existing protocol: verify/reuse, do not overwrite')
    OUT.mkdir(parents=True, exist_ok=True)
    package = parent_verified()
    ledger = json.loads((PARENT / 'case_ledger.json').read_text())
    refs = []
    with zipfile.ZipFile(package['retrieved']) as z:
        for case in ledger['cases']:
            body = z.read('raw/case_' + case['symbol'] + '.html')
            if hashlib.sha256(body).hexdigest() != case['document_index_sha256']:
                raise ValueError('Parent case bytes differ')
            p = BidderReferences()
            p.feed(body.decode())
            if len(p.rows) - 1 != len(case['documents']):
                raise ValueError('Reference/text row count differs')
            for i, (row, doc) in enumerate(zip(p.rows[1:], case['documents'])):
                refs.append(dict(symbol=case['symbol'], document_index=i, document=doc,
                    parent_source_sha256=case['document_index_sha256'], request=request_for_pointer(row, doc, case['symbol'], i)))
    atomic_json(OUT / 'references.json', refs)
    policy = dict(purpose='Bounded original-content/source audit only; no market quotes, returns, model fitting or parameter changes',
                  parent_checkpoint_sha256=sha256(PARENT / 'checkpoint.json'), parent_archive_sha256=package['sha256'],
                  references_sha256=sha256(OUT / 'references.json'), references=len(refs), cases=12,
                  pilot='6938 initial filing, prospectus and expiry notice plus one date-filter control using firstin=1; max4 requests',
                  full_acquisition='Only after pilot exposes usable document/notice routes: remaining fixed references once; max103 reference requests inclusive of pilot',
                  pdf_followups='At most one HTML-discovered HTTPS TWSE-hosted PDF per gateway; max53; no script execution or invented filenames',
                  scope_checks='At most3 additional official form-derived boundary/control queries; preserve any range mismatch and pre-commencement coverage unknown',
                  workers=2, request_timeout_seconds=30, per_response_bytes=33554432,
                  stop='Do not turn inaccessible sources into a manual download queue; record actual transport/content refusal and unknown PIT. No return study unless separate source and economic protocol gates pass',
                  timestamps='Index reported time, form DATE parameter, document text date and retrieval time remain separate; latest retrieval never proves earliest public availability')
    atomic_json(POLICY, policy)
    atomic_json(OUT / 'protocol_freeze.json', dict(frozen_at=utcnow(),protocol_sha256=sha256(POLICY),prices_or_returns_examined=False))
    pilot = [r['request'] for r in refs if r['symbol'] == '6938' and r['document_index'] in [0,1,7]]
    pilot.append(dict(filename='filter_control.html',url='https://mopsov.twse.com.tw/mops/web/ajax_t162sb03',method='POST',data='step=1&firstin=1&off=1&start_YM=11301&end_YM=11412&achieved=&cert_type='))
    write_batch('pilot', pilot)


def policy():
    c = json.loads(POLICY.read_text())
    if sha256(POLICY) != json.loads((OUT / 'protocol_freeze.json').read_text())['protocol_sha256'] or sha256(PARENT / 'checkpoint.json') != c['parent_checkpoint_sha256'] or sha256(OUT / 'references.json') != c['references_sha256']:
        raise ValueError('Frozen original-content protocol/parent/references drift')
    return c


def write_batch(tag, requests):
    cfg = Path('configs/tender_originals_' + tag + '_sources.json')
    atomic_json(cfg, dict(output_directory=str(ROOT / ('raw_' + tag)),allowed_hosts=['mopsov.twse.com.tw','doc.twse.com.tw'],requests=requests))
    common = ['tender_originals.py','tender_preflight.py','source_checkpoint.py','prospective_sources.py','research_runtime.py',str(POLICY),str(OUT / 'protocol_freeze.json'),str(OUT / 'references.json'),str(cfg),str(PARENT / 'checkpoint.json')]
    plan = dict(stages=[dict(id='acquire',command=['{python}','bounded_public_sources.py',str(cfg)],inputs=common+['bounded_public_sources.py'],outputs=[str(ROOT / ('raw_' + tag) / 'results.json')],timeout_seconds=600),
                       dict(id='package',command=['{python}','tender_originals.py','package','--tag',tag],inputs=common+[str(ROOT / ('raw_' + tag))],outputs=[str(ROOT / (tag+'.zip')),str(OUT / (tag+'_package.json'))],timeout_seconds=60)])
    atomic_json('configs/tender_originals_' + tag + '_pipeline.json',plan)


def package(tag):
    policy()
    cfgpath = Path('configs/tender_originals_' + tag + '_sources.json')
    cfg = json.loads(cfgpath.read_text())
    raw = ROOT / ('raw_' + tag)
    result = json.loads((raw / 'results.json').read_text())
    if result['config_sha256'] != sha256(cfgpath):
        raise ValueError('Acquisition config differs')
    verified_records(cfg,result,lambda n:(raw/n).read_bytes())
    entries = {'protocol.json':POLICY,'references.json':OUT/'references.json','requests.json':cfgpath}
    if tag.startswith('recovery'):
        entries['recovery_protocol.json'] = OUT/'recovery_protocol.json'
    entries.update({'raw/'+p.name:p for p in raw.iterdir() if p.is_file()})
    with exclusive_lock(ROOT/'acquisition.lock'):
        package_sources(ROOT,OUT,tag,entries)


def prepare_references():
    policy()
    refs = json.loads((OUT / 'references.json').read_text())
    pilot = json.loads(Path('configs/tender_originals_pilot_sources.json').read_text())
    done = {r['filename'] for r in pilot['requests']}
    todo = [r['request'] for r in refs if r['request']['filename'] not in done]
    for i in range(0,len(todo),30):
        write_batch('refs'+str(i//30+1).zfill(2),todo[i:i+30])


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self,tag,attrs):
        a = dict(attrs)
        if tag == 'a' and 'href' in a:
            self.links.append(a['href'])


def pdf_request(body, expected):
    if body.startswith(b'%PDF-'):
        return None
    parser = Links()
    # Gateway labels use Big5, but ASCII URLs must never be inferred from prose.
    parser.feed(body.decode('big5', errors='replace'))
    links = [urljoin('https://doc.twse.com.tw',u) for u in parser.links]
    links = [u for u in links if urlsplit(u).path.lower().endswith('.pdf')]
    if len(links) != 1:
        raise ValueError('Missing/ambiguous generated PDF link')
    u = urlsplit(links[0])
    stem = re.escape(expected[:-4])
    if u.scheme != 'https' or u.netloc != 'doc.twse.com.tw' or u.query or not re.fullmatch('/pdf/'+stem+r'(?:_\d{8}_\d{6})?\.pdf',u.path):
        raise ValueError('Generated PDF outside exact expected document/host')
    return links[0]


def prepare_pdfs():
    policy()
    requests = []
    provenance = []
    for ref in json.loads((OUT / 'references.json').read_text()):
        if ref['document']['filename'] is None:
            continue
        paths = [p for p in ROOT.glob('raw_*/'+ref['request']['filename']) if p.parent.name=='raw_pilot' or p.parent.name.startswith('raw_refs')]
        if len(paths) != 1:
            raise ValueError('Missing/duplicate raw gateway')
        raw = paths[0]
        meta = json.loads(raw.with_name(raw.name+'.meta.json').read_text())
        if meta.get('http_status') != 200 or meta.get('exit_code') != 0 or sha256(raw) != meta['sha256']:
            provenance.append(dict(pointer=ref['request']['filename'],gateway_path=str(raw),status='gateway_unavailable'))
            continue
        try:
            url = pdf_request(raw.read_bytes(),ref['document']['filename'])
            status = 'direct_pdf' if url is None else 'discovered_pdf_link'
        except ValueError as e:
            provenance.append(dict(pointer=ref['request']['filename'],gateway_path=str(raw),gateway_sha256=sha256(raw),status='no_usable_pdf_link',reason=str(e)))
            continue
        provenance.append(dict(pointer=ref['request']['filename'],gateway_path=str(raw),gateway_sha256=sha256(raw),status=status,url=url))
        if url:
            requests.append(dict(filename=raw.stem+'.pdf',url=url))
    atomic_json(OUT/'pdf_link_provenance.json',provenance)
    if len(requests)>53:
        raise ValueError('PDF followup budget exceeded')
    for i in range(0,len(requests),30):
        write_batch('pdfs'+str(i//30+1).zfill(2),requests[i:i+30])


def prepare_recovered_pdfs():
    policy()
    phase = json.loads((OUT/'recovery_protocol.json').read_text())
    if phase['parent_protocol_sha256'] != sha256(POLICY) or phase['prior_provenance_sha256'] != sha256(OUT/'pdf_link_provenance.json'):
        raise ValueError('Recovery parent/provenance differs')
    refs = {r['request']['filename']:r for r in json.loads((OUT/'references.json').read_text())}
    cfg = json.loads(Path('configs/tender_originals_recovery_sources.json').read_text())
    requests, provenance = [], []
    for req in cfg['requests']:
        raw = ROOT/'raw_recovery'/req['filename']
        meta = json.loads(raw.with_name(raw.name+'.meta.json').read_text())
        item = dict(pointer=req['filename'],status='gateway_unavailable',gateway_path=str(raw))
        if raw.exists() and meta.get('http_status')==200 and meta.get('exit_code')==0:
            if sha256(raw)!=meta['sha256']:
                raise ValueError('Recovery body drift')
            try:
                url = pdf_request(raw.read_bytes(),refs[req['filename']]['document']['filename'])
                item.update(status='discovered_pdf_link' if url else 'direct_pdf',url=url,gateway_sha256=sha256(raw))
                if url:
                    requests.append(dict(filename=raw.stem+'.pdf',url=url))
            except ValueError as e:
                item.update(status='no_usable_pdf_link',reason=str(e))
        provenance.append(item)
    if len(requests)>phase['maximum_discovered_pdf_followups']:
        raise ValueError('Recovery followup budget exceeded')
    atomic_json(OUT/'recovery_pdf_provenance.json',provenance)
    if requests:
        write_batch('recoverypdf',requests)


class PreText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.active = False

    def handle_starttag(self,tag,attrs):
        if tag == 'pre':
            self.blocks.append([])
            self.active = True
        elif tag == 'br' and self.active:
            self.blocks[-1].append('\n')

    def handle_endtag(self,tag):
        if tag == 'pre':
            self.active = False

    def handle_data(self,data):
        if self.active:
            self.blocks[-1].append(data)


def notice(body, symbol):
    tables = table_text(body)
    if not tables:
        raise ValueError('Missing official announcement body')
    cells = [c for row in tables[0] for c in row]
    ids = [c for c in cells if re.match(r'被收購公司代號[：:]', c)]
    if ids != ['被收購公司代號：'+symbol]:
        raise ValueError('Wrong/missing target identity in announcement body')
    parser = PreText()
    parser.feed(body.decode('utf-8-sig'))
    blocks = [''.join(b).strip() for b in parser.blocks]
    if len(blocks)<2:
        raise ValueError('Missing announcement subject/content')
    content = '\n'.join(blocks[1:])
    matches = re.findall(r'實際成交數量\s*(?:[：:]|為)\s*((?:\d{1,3}(?:,\d{3})+|\d+))\s*股',content)
    if len(set(matches))>1:
        raise ValueError('Ambiguous declared actual share quantity')
    return dict(subject=blocks[0],content=content,
                declared_actual_shares=int(matches[0].replace(',','')) if matches else None,
                fact_date_fields=[c for c in cells if c.startswith('事實發生日')],
                original_content_identity_verified=True, first_public_availability_verified=False,
                actual_broker_settlement_verified=False)


def archived_sources():
    policy()
    batches, records, receipts = {}, [], []
    configs = sorted(Path('configs').glob('tender_originals_*_sources.json'))
    for cfgpath in configs:
        tag = cfgpath.name[len('tender_originals_'):-len('_sources.json')]
        pkg, transfer = readback(OUT,tag)
        with zipfile.ZipFile(pkg['retrieved']) as z:
            stored = {n:z.read(n) for n in z.namelist()}
        for n,path in [('protocol.json',POLICY),('references.json',OUT/'references.json'),('requests.json',cfgpath)]:
            if hashlib.sha256(stored[n]).hexdigest()!=sha256(path):
                raise ValueError('Archived original audit configuration drift')
        if tag.startswith('recovery') and hashlib.sha256(stored['recovery_protocol.json']).hexdigest()!=sha256(OUT/'recovery_protocol.json'):
            raise ValueError('Archived recovery protocol drift')
        result = json.loads(stored['raw/results.json'])
        if result['config_sha256']!=sha256(cfgpath):
            raise ValueError('Archived request cohort drift')
        verified_records(json.loads(cfgpath.read_text()),result,lambda n:stored['raw/'+n])
        batches[tag]=stored
        for r in result['requests']:
            records.append(dict(batch=tag,**r))
        receipts.append(dict(batch=tag,archive_sha256=pkg['sha256'],manifest_files=pkg['manifest_files'],backup=transfer))
    atomic_json(OUT/'source_receipt.json',dict(roundtrip_verified=True,crc_manifest_verified=True,batches=receipts,
                configured_requests=len(records),attempted_requests=sum(not r.get('not_requested_reason') for r in records),responses_with_body=sum('sha256' in r for r in records),
                observations=[dict(batch=r['batch'],filename=r['request']['filename'],http_status=r.get('http_status'),exit_code=r.get('exit_code'),size_bytes=r.get('size_bytes'),sha256=r.get('sha256'),request_started_at=r.get('request_started_at'),observed_at=r.get('observed_at'),quota_refusal=r.get('quota_refusal'),not_requested_reason=r.get('not_requested_reason'),transport_stderr=r.get('stderr','') if r.get('exit_code')!=0 else '') for r in records]))
    return batches, records


def replay():
    from pypdf import PdfReader
    from tender_preflight import parse_filings,parse_index
    batches, records = archived_sources()
    refs = json.loads((OUT/'references.json').read_text())
    documents = []
    textroot = ROOT/'text'
    textroot.mkdir(exist_ok=True)
    for ref in refs:
        filename = ref['request']['filename']
        candidates = [r for r in records if r['request']['filename']==filename]
        if any(r['request']!=ref['request'] for r in candidates):
            raise ValueError('Original pointer request differs from frozen reference')
        row = dict(symbol=ref['symbol'],document_index=ref['document_index'],title=ref['document']['title'],
                   reported_timestamp_taipei=ref['document']['reported_timestamp_taipei'],reference_filename=ref['document']['filename'],
                   form_request=ref['request'],original_content_verified=False,historical_pit_verified=False,
                   attempts=[dict(batch=r['batch'],http_status=r.get('http_status'),exit_code=r.get('exit_code'),sha256=r.get('sha256')) for r in candidates])
        if ref['document']['filename'] is None:
            good = [r for r in candidates if r.get('http_status')==200 and r.get('exit_code')==0]
            if len(good)==1:
                record=good[0];body=batches[record['batch']]['raw/'+filename]
                try:
                    parsed=notice(body,ref['symbol'])
                    content=parsed.pop('content');row.update(parsed,source_sha256=hashlib.sha256(body).hexdigest(),original_content_verified=True)
                    data=content.encode();path=textroot/(filename+'.txt.gz');path.write_bytes(gzip.compress(data,mtime=0))
                    row.update(extracted_text_path=str(path),extracted_text_sha256=sha256(path))
                except ValueError as e:
                    row['failure']=str(e)
            else:
                row['failure']='Announcement transport unavailable/ambiguous'
        else:
            name=Path(filename).stem+'.pdf'
            good=[r for r in records if r['request']['filename']==name and r.get('http_status')==200 and r.get('exit_code')==0]
            if len(good)==1:
                record=good[0];body=batches[record['batch']]['raw/'+name]
                try:
                    matching_gateways=[r for r in candidates if r.get('http_status')==200 and r.get('exit_code')==0 and 'raw/'+filename in batches[r['batch']]]
                    allowed=[]
                    for r in matching_gateways:
                        try:
                            allowed.append(pdf_request(batches[r['batch']]['raw/'+filename],ref['document']['filename']))
                        except ValueError:
                            pass
                    if record['request']['url'] not in allowed:
                        raise ValueError('PDF transport URL differs from archived gateway link')
                    if not body.startswith(b'%PDF-'):
                        raise ValueError('HTTP200 body is not PDF')
                    reader=PdfReader(BytesIO(body))
                    pages=[p.extract_text() or '' for p in reader.pages]
                    data='\n'.join(pages).encode();path=textroot/(name+'.txt.gz');path.write_bytes(gzip.compress(data,mtime=0))
                    row.update(original_content_verified=True,source_sha256=hashlib.sha256(body).hexdigest(),pages=len(pages),
                        extracted_text_characters=len(data.decode()),extracted_text_path=str(path),extracted_text_sha256=sha256(path),
                        target_symbol_in_extracted_text=ref['symbol'] in data.decode(),all_terms_semantically_verified=False)
                except Exception as e:
                    row['failure']=type(e).__name__+': '+str(e)
            else:
                row['failure']='No single verified PDF response; never treat HTML gateway as original'
        documents.append(row)
    expiry=[r for r in documents if '公開收購期間屆滿' in r['title']]
    case_rows=json.loads((PARENT/'case_ledger.json').read_text())['cases']
    reconciled=[]
    for case in case_rows:
        es=[r for r in expiry if r['symbol']==case['symbol']]
        declared=es[0].get('declared_actual_shares') if len(es)==1 else None
        reconciled.append(dict(symbol=case['symbol'],summary_reported_actual_shares=case['filing']['reported_actual_shares'],
            expiry_declared_actual_shares=declared,summary_value_replaced=False,
            expiry_source_sha256=es[0].get('source_sha256') if len(es)==1 else None,
            documents_received=sum(d['original_content_verified'] for d in documents if d['symbol']==case['symbol']),
            documents_expected=sum(d['symbol']==case['symbol'] for d in documents),
            actual_cash_or_delivery_verified=False,historical_pit_verified=False))
    controls={}
    for r in records:
        n=r['request']['filename']
        if n not in ['filter_control.html','failed_only_control.html','start_year_2023.html','start_year_2025.html']:
            continue
        item=dict(http_status=r.get('http_status'),exit_code=r.get('exit_code'),source_sha256=r.get('sha256'))
        try:
            if r.get('http_status')!=200 or r.get('exit_code')!=0:
                raise ValueError('Control transport unavailable')
            body=batches[r['batch']]['raw/'+n]
            if 'start_year' in n:
                year=112 if '2023' in n else 114
                values=parse_index(body,year)
                item.update(rows=len(values),filing_year_boundary_rows=[v for v in values if not v['filed_roc'].startswith(str(year)+'/')],requested_year_verified=True)
            else:
                values=parse_filings(body)
                item.update(rows=len(values),outside_requested_period_symbols=[v['symbol'] for v in values if not v['start'] or not '2024-01-01'<=v['start']<=('2024-12-31' if n=='failed_only_control.html' else '2025-12-31')],
                    unexpected_success_symbols=[v['symbol'] for v in values if n=='failed_only_control.html' and v['reported_outcome']!='失敗'])
        except ValueError as e:
            item['failure']=str(e)
        controls[n]=item
    atomic_json(OUT/'document_ledger.json',dict(documents=documents,cases=reconciled,controls=controls))
    atomic_json(OUT/'decision.json',dict(status='original_source_audit_only_no_returns',references=len(refs),
        originals_received=sum(r['original_content_verified'] for r in documents),
        pdfs_received=sum(r['original_content_verified'] and r['reference_filename'] is not None for r in documents),
        notices_received=sum(r['original_content_verified'] and r['reference_filename'] is None for r in documents),
        expiry_notices_received=sum(r['original_content_verified'] for r in expiry),
        missing_originals=[dict(symbol=r['symbol'],document_index=r['document_index'],title=r['title'],failure=r.get('failure')) for r in documents if not r['original_content_verified']],
        reconciliation_6938=next(r for r in reconciled if r['symbol']=='6938'),
        all_originals_received=all(r['original_content_verified'] for r in documents),
        all_terms_semantically_verified=False,cohort_proposals_and_withdrawals_complete=False,
        historical_pit_verified=False,actual_cash_or_delivery_verified=False,return_study_gate_passed=False,
        valid_prospective_signals=0,no_user_manual_download_requests=True))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage',choices=['freeze','package','prepare_references','prepare_pdfs','prepare_recovered_pdfs','replay'])
    p.add_argument('--tag',default='pilot')
    args = p.parse_args()
    package(args.tag) if args.stage == 'package' else globals()[args.stage]()
