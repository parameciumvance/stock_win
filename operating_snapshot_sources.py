"""Read the already backed-up source graph without downloading or mutating it."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
from source_checkpoint import readback


def verified_members(data,expected_sha=None):
    if expected_sha and hashlib.sha256(data).hexdigest()!=expected_sha:
        raise ValueError('Archive digest mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or z.testzip() is not None:raise ValueError('Archive duplicate/CRC failure')
        manifest=json.loads(z.read('manifest.json'))
        if set(names)!=set(manifest)|{'manifest.json'}:raise ValueError('Archive manifest member mismatch')
        entries={name:z.read(name) for name in manifest}
        if any(hashlib.sha256(entries[name]).hexdigest()!=h for name,h in manifest.items()):raise ValueError('Archive member digest mismatch')
        return entries


class SnapshotSources:
    def __init__(self,out,expected_sha):
        self.receipt,self.transfer=readback(out,'final')
        if self.receipt['sha256']!=expected_sha:raise ValueError('Wrong frozen raw checkpoint')
        self.top=verified_members(Path(self.receipt['retrieved']).read_bytes(),expected_sha)
        self.pack=verified_members(self.top['prior/pdf.zip'],json.loads(self.top['prior/pdf_package.json'])['sha256'])
        self.selected=json.loads(self.pack['selected_sources.json'])
        self.records={r['request']['filename']:r for r in json.loads(self.pack['raw/results.json'])['requests']}
        self.fallback=json.loads(self.top['fallback/results.json'])['requests'][0]
        self.cache={}
        pairs=[(s['issuer'],s['quarter']) for s in self.selected]
        if len(pairs)!=len(set(pairs)):raise ValueError('Duplicate issuer-quarter source')

    def document(self,source):
        issuer,q=source['issuer'],source['quarter'];management=False
        if source['kind']=='frozen_reuse':
            if issuer not in self.cache:
                label='umc' if issuer=='2303' else 'tsmc'
                receipt=json.loads(self.pack['prior/'+label+'_receipt.json'])
                raw=verified_members(self.pack[source['source']],receipt['sha256'])
                if issuer=='2330':
                    raw=verified_members(raw['prior/source_archive.zip'],json.loads(raw['prior/checkpoint.json'])['sha256'])
                    raw=verified_members(raw['prior/tsmc.zip'],json.loads(raw['prior/tsmc_receipt.json'])['sha256'])
                self.cache[issuer]=raw
            raw=self.cache[issuer];name='raw/umc_2024Q4_official.pdf' if issuer=='2303' else 'curl/tsmc_2024Q4.pdf'
            body=raw[name];meta=json.loads(raw[name+'.meta.json']);url=meta['url']
        else:
            meta=self.records[source['filename']];url=source['url']
            if meta['http_status']==200:
                body=self.pack['raw/'+source['filename']]
            elif (issuer,q)==('2330','2023Q2') and self.fallback['http_status']==200:
                meta=self.fallback;body=self.top['fallback/tsmc_2023Q2_management.pdf'];url=meta['request']['url'];management=True
            else:raise ValueError('No verified original for '+issuer+' '+q)
        digest=hashlib.sha256(body).hexdigest()
        if digest!=meta['sha256'] or not body.startswith(b'%PDF-'):raise ValueError('Document hash/type mismatch')
        if len(body)!=meta['size_bytes']:raise ValueError('Document length mismatch')
        return dict(issuer=issuer,quarter=q,body=body,sha256=digest,url=url,management=management,observed_at=meta.get('observed_at'))
