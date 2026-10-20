"""Frozen source census supplement; never mutates the earlier pilot or queries prices."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from native_public_sources import acquire as native_acquire
from research_runtime import atomic_bytes, atomic_json, exclusive_lock, sha256
from source_checkpoint import package_sources, readback
from tender_preflight import verified_records

ROOT = Path('inputs/buyback_coverage_20261020')
OUT = Path('deliverables/buyback_coverage_20261020')
POLICY = Path('configs/buyback_coverage_protocol_20261020.json')
OLD = Path('deliverables/buyback_preflight_20261020')


def policy():
    if sha256(POLICY) != json.loads((OUT/'protocol_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Coverage protocol drift')
    p = json.loads(POLICY.read_text())
    for name, h in p['prior_checkpoints'].items():
        if sha256(name) != h:
            raise ValueError('Prior checkpoint drift: '+name)
        for f, expected in json.loads(Path(name).read_text())['files'].items():
            if sha256(f) != expected:
                raise ValueError('Prior frozen member drift: '+f)
    if sha256(OUT/'selection.json') != p['selection_manifest_sha256']:
        raise ValueError('Original census selection drift')
    count = 0
    for b in p['batches'].values():
        if sha256(b['path']) != b['sha256']:
            raise ValueError('Frozen source config drift')
        c = json.loads(Path(b['path']).read_text())
        if len(c['requests']) != b['requests']:
            raise ValueError('Batch size drift')
        count += len(c['requests'])
    if count != p['max_saved_requests'] or len(p['batches']) != p['max_source_batches']:
        raise ValueError('Source budget drift')
    return p


def config(batch):
    p = policy()
    if batch=='recovery':
        path=Path('configs/buyback_coverage_recovery_protocol_20261020.json')
        if sha256(path)!=json.loads((OUT/'recovery_freeze.json').read_text())['protocol_sha256']:
            raise ValueError('Recovery protocol drift')
        repair=json.loads(path.read_text())
        if sha256(OUT/'originals04_receipt.json')!=repair['failed_receipt_sha256']:
            raise ValueError('Failed source receipt drift')
        path=Path(repair['request_config'])
        if sha256(path)!=repair['request_config_sha256']:
            raise ValueError('Recovery config drift')
        cfg=json.loads(path.read_text())
        if len(cfg['requests'])!=1 or cfg['requests'][0]['url']!=repair['url']:
            raise ValueError('Recovery must be exactly one failed URL')
        return path,cfg
    path = Path(p['batches'][batch]['path'])
    return path, json.loads(path.read_text())


def archived(batch):
    path, cfg = config(batch)
    pkg, transfer = readback(OUT,batch)
    with zipfile.ZipFile(pkg['retrieved']) as z:
        if z.read('protocol.json') != POLICY.read_bytes() or z.read('requests.json') != path.read_bytes() or z.read('selection.json') != (OUT/'selection.json').read_bytes():
            raise ValueError('Archived source policy/config drift')
        if batch=='recovery' and z.read('recovery_protocol.json')!=Path('configs/buyback_coverage_recovery_protocol_20261020.json').read_bytes():
            raise ValueError('Archived recovery protocol drift')
        result = json.loads(z.read('raw/results.json'))
        if result['config_sha256'] != sha256(path):
            raise ValueError('Archived source config hash mismatch')
        records = verified_records(cfg,result,lambda n:z.read('raw/'+n))
        files = {r['request']['filename']: z.read('raw/'+r['request']['filename']) for r in records if 'sha256' in r}
    return pkg, transfer, records, files


def source_gate(batch):
    if batch in ['index','recovery']:
        return
    r = json.loads((OUT/'partition_audit.json').read_text())
    pkg = json.loads((OUT/'index_package.json').read_text())
    if not r['current_snapshot_partition_agreement'] or r['index_package_sha256'] != pkg['sha256'] or r['protocol_sha256'] != sha256(POLICY):
        raise ValueError('Year/month partition gate must pass before original census')
    names = list(policy()['batches'])
    for previous in names[1:names.index(batch)]:
        receipt = json.loads((OUT/(previous+'_receipt.json')).read_text())
        if not receipt['all_transport_passed']:
            raise ValueError('Previous source batch transport failed')
        if not receipt.get('all_identities_verified',False):
            raise ValueError('Previous source batch identity/schema validation failed')


def acquire(batch):
    source_gate(batch)
    path, cfg = config(batch)
    raw = Path(cfg['output_directory'])
    if (OUT/(batch+'_package.json')).exists():
        pkg, _, _, _ = archived(batch)
        with exclusive_lock(ROOT/'acquisition.lock'), zipfile.ZipFile(pkg['retrieved']) as z:
            for member in z.namelist():
                if not member.startswith('raw/'):
                    continue
                name = member[4:]
                if not name or Path(name).name != name:
                    raise ValueError('Unsafe raw restore path')
                dest, data = raw/name, z.read(member)
                if dest.exists() and dest.read_bytes() != data:
                    raise ValueError('Local source differs; never overwritten: '+name)
                if not dest.exists():
                    atomic_bytes(dest,data)
    elif (raw/'results.json').exists():
        result=json.loads((raw/'results.json').read_text())
        verified_records(cfg,result,lambda n:(raw/n).read_bytes())
    native_acquire(path)


def package(batch):
    path,cfg=config(batch);raw=Path(cfg['output_directory'])
    result=json.loads((raw/'results.json').read_text())
    if result['config_sha256']!=sha256(path):
        raise ValueError('Source config changed after acquisition')
    verified_records(cfg,result,lambda n:(raw/n).read_bytes())
    entries={'protocol.json':POLICY,'requests.json':path,'selection.json':OUT/'selection.json'}
    if batch=='recovery':
        entries['recovery_protocol.json']=Path('configs/buyback_coverage_recovery_protocol_20261020.json')
    entries.update({'raw/'+f.name:f for f in raw.iterdir() if f.is_file()})
    with exclusive_lock(ROOT/'acquisition.lock'):
        if (OUT/(batch+'_package.json')).exists():
            pkg,_=readback(OUT,batch)
            with zipfile.ZipFile(pkg['retrieved']) as z:
                manifest=json.loads(z.read('manifest.json'))
            if {n:sha256(f) for n,f in entries.items()}!=manifest:
                raise ValueError('Saved source package differs; not replaced')
        package_sources(ROOT,OUT,batch,entries)


def inspect(batch):
    pkg,transfer,records,files=archived(batch)
    rows=[{k:r.get(k) for k in ['request','http_status','exit_code','size_bytes','sha256','request_started_at','observed_at','error']}|{'effective_url':r.get('curl',{}).get('url_effective'),'stderr':r.get('stderr','') if r.get('exit_code')!=0 else ''} for r in records]
    passed=all(r.get('http_status')==200 and r.get('exit_code')==0 for r in records)
    receipt=dict(archive_sha256=pkg['sha256'],manifest_files=pkg['manifest_files'],backup=transfer,sha_crc_manifest_verified=True,observations=rows,all_transport_passed=passed,historical_pit_verified=False)
    errors=[]
    if batch!='index' and passed:
        from buyback_document_identity import parse_identity
        selections={r['filename']:r for r in json.loads((OUT/'selection.json').read_text())['requests'] if r['batch']==batch}
        if batch=='recovery':
            repair=json.loads(Path('configs/buyback_coverage_recovery_protocol_20261020.json').read_text())
            selection=next(r for r in json.loads((OUT/'selection.json').read_text())['requests'] if r['batch']==repair['failed_batch'] and r['filename']==repair['failed_filename'])
            selections={repair['replacement_filename']:selection}
        identities=[]
        for record in records:
            name=record['request']['filename'];selection=selections[name]
            try:
                doc=parse_identity(files[name],selection['original_fields'])
                identities.append(dict(event_id=selection['event_id'],filename=name,issuer=doc['issuer'],reported_datetime=doc['reported_datetime'],document_form=doc['document_form'],required_schema_known=doc['required_schema_known'],description_sha256=doc['description_sha256']))
            except (ValueError,UnicodeError,KeyError) as error:
                errors.append(dict(event_id=selection['event_id'],filename=name,type=type(error).__name__,error=str(error)))
        receipt.update(identities=identities,identity_errors=errors,all_identities_verified=not errors)
    atomic_json(OUT/(batch+'_receipt.json'),receipt)
    if not passed:
        raise ValueError('Actual transport failure preserved; no downstream source parsing')
    if errors:
        raise ValueError('Saved original identity/schema validation failed; inspect receipt')


def reconcile():
    from buyback_index_reconcile import reconcile as run
    policy();pkg,_,records,files=archived('index')
    required=[r for r in records if r['request']['filename'].endswith('.json')]
    if any(r.get('http_status')!=200 or r.get('exit_code')!=0 for r in required):
        raise ValueError('Index transport failure')
    old,_=readback(OLD,'query')
    with zipfile.ZipFile(old['retrieved']) as z:
        baseline=z.read('raw/announcements_2024.json')
    p=policy()
    if hashlib.sha256(baseline).hexdigest()!=p['frozen_baseline_raw_index_sha256']:
        raise ValueError('Baseline raw index drift')
    result=run(baseline,{f'2024-{m:02d}':files[f'2024_{m:02d}.json'] for m in range(1,13)},{k:files[k+'.json'] for k in ['2023Q4','2025Q1']})
    result.update(index_package_sha256=pkg['sha256'],protocol_sha256=sha256(POLICY))
    # Full index bodies remain in the saved archive; preserve compact differences.
    atomic_json(ROOT/'partition_full.json',result)
    summary={k:v for k,v in result.items() if k not in ['annual_index','monthly_indices','boundary_indices']}
    summary['boundary_counts']={k:len(v['rows']) for k,v in result['boundary_indices'].items()}
    atomic_json(OUT/'partition_audit.json',summary)
    print(json.dumps({'partition_agreement':result['current_snapshot_partition_agreement'],'monthly_counts':result['monthly_counts'],'boundary_counts':summary['boundary_counts']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['acquire','package','inspect','reconcile']);parser.add_argument('--batch',default='index')
    args=parser.parse_args()
    reconcile() if args.stage=='reconcile' else globals()[args.stage](args.batch)
