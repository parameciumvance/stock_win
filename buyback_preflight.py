"""Bounded repurchase-source trial; no prices, signals or backtest engine."""
import argparse
import json
from pathlib import Path
import zipfile

from research_runtime import atomic_bytes, atomic_json, exclusive_lock, sha256
from source_checkpoint import package_sources, readback
from tender_preflight import verified_records

ROOT = Path('inputs/buyback_preflight_20261020')
OUT = Path('deliverables/buyback_preflight_20261020')
POLICY = Path('configs/buyback_preflight_protocol_20261020.json')
REQUESTS = Path('configs/buyback_preflight_sources_20261020.json')
TAG = 'sources'


def policy():
    p = json.loads(POLICY.read_text())
    if sha256(POLICY) != json.loads((OUT / 'protocol_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Frozen source protocol drift')
    for name, digest in p['request_configs_sha256'].items():
        if sha256(name) != digest:
            raise ValueError('Frozen request configuration drift')
    if TAG != 'sources':
        freeze = json.loads((OUT / (TAG + '_freeze.json')).read_text())
        if freeze['request_config_sha256'] != sha256(REQUESTS) or freeze['protocol_sha256'] != sha256(POLICY):
            raise ValueError('Frozen followup configuration drift')
        if TAG == 'originals':
            original = Path('configs/buyback_originals_protocol_20261020.json')
            op = json.loads(original.read_text())
            if sha256(original) != freeze['originals_protocol_sha256'] or sha256(OUT / 'originals_selection.json') != op['selection_manifest_sha256']:
                raise ValueError('Original document pilot drift')
            if op['parent_protocol_sha256'] != sha256(POLICY) or op['request_config_sha256'] != sha256(REQUESTS):
                raise ValueError('Original pilot parent or request drift')
    for name, digest in p['prior_checkpoints'].items():
        if sha256(name) != digest:
            raise ValueError('Prior checkpoint drift')
        for file, expected in json.loads(Path(name).read_text())['files'].items():
            if sha256(file) != expected:
                raise ValueError('Frozen prior output drift: ' + file)
    return p


def package():
    p = policy()
    cfg = json.loads(REQUESTS.read_text())
    raw = Path(cfg['output_directory'])
    limit = {'sources': 5, 'discovery': 4, 'query': 1, 'originals': 7}[TAG]
    if len(cfg['requests']) > limit:
        raise ValueError('Request budget exceeded')
    result = json.loads((raw / 'results.json').read_text())
    if result['config_sha256'] != sha256(REQUESTS):
        raise ValueError('Acquisition configuration drift')
    verified_records(cfg, result, lambda n: (raw / n).read_bytes())
    entries = {'protocol.json': POLICY, 'requests.json': REQUESTS}
    if TAG == 'originals':
        entries['originals_protocol.json'] = Path('configs/buyback_originals_protocol_20261020.json')
        entries['originals_selection.json'] = OUT / 'originals_selection.json'
    entries.update({'raw/' + f.name: f for f in raw.iterdir() if f.is_file()})
    with exclusive_lock(ROOT / 'acquisition.lock'):
        if (OUT / (TAG + '_package.json')).exists():
            pkg, _ = readback(OUT, TAG)
            with zipfile.ZipFile(pkg['retrieved']) as z:
                manifest = json.loads(z.read('manifest.json'))
            if {name: sha256(file) for name, file in entries.items()} != manifest:
                raise ValueError('Frozen source package differs; not replaced')
        package_sources(ROOT, OUT, TAG, entries)


def acquire():
    """Validate the frozen request plan; restore saved sources before any live I/O."""
    from native_public_sources import acquire as native_acquire
    policy()
    cfg = json.loads(REQUESTS.read_text())
    if len(cfg['requests']) > {'sources': 5, 'discovery': 4, 'query': 1, 'originals': 7}[TAG]:
        raise ValueError('Request budget exceeded before acquisition')
    raw = Path(cfg['output_directory'])
    if (OUT / (TAG + '_package.json')).exists():
        pkg, _ = readback(OUT, TAG)
        with exclusive_lock(ROOT / 'acquisition.lock'), zipfile.ZipFile(pkg['retrieved']) as z:
            if z.read('requests.json') != REQUESTS.read_bytes():
                raise ValueError('Saved request plan drift; no live replacement')
            for member in z.namelist():
                if not member.startswith('raw/'):
                    continue
                name = member.removeprefix('raw/')
                if not name or Path(name).name != name:
                    raise ValueError('Unsafe saved source path')
                dest, body = raw / name, z.read(member)
                if dest.exists() and dest.read_bytes() != body:
                    raise ValueError('Local saved source drift; not overwritten: ' + name)
                if not dest.exists():
                    atomic_bytes(dest, body)
    elif (raw / 'results.json').exists():
        result = json.loads((raw / 'results.json').read_text())
        verified_records(cfg, result, lambda name: (raw / name).read_bytes())
    native_acquire(REQUESTS)


def inspect():
    from buyback_source_inspection import inspect_response
    policy()
    pkg, transfer = readback(OUT, TAG)
    cfg = json.loads(REQUESTS.read_text())
    with zipfile.ZipFile(pkg['retrieved']) as z:
        if z.read('protocol.json') != POLICY.read_bytes() or z.read('requests.json') != REQUESTS.read_bytes():
            raise ValueError('Archived policy/request drift')
        if TAG == 'originals' and (z.read('originals_protocol.json') != Path('configs/buyback_originals_protocol_20261020.json').read_bytes()
                or z.read('originals_selection.json') != (OUT / 'originals_selection.json').read_bytes()):
            raise ValueError('Archived original-pilot protocol/selection drift')
        result = json.loads(z.read('raw/results.json'))
        if result['config_sha256'] != sha256(REQUESTS):
            raise ValueError('Archived configuration hash drift')
        records = verified_records(cfg, result, lambda n: z.read('raw/' + n))
        rows = []
        for r in records:
            name = r['request']['filename']
            body = z.read('raw/' + name) if 'sha256' in r else b''
            effective = r.get('curl', {}).get('url_effective', r['request']['url'])
            kind = 'pdf' if name.endswith('.pdf') else 'javascript' if name.endswith('.js') else 'json' if name.endswith('.json') else 'html'
            details = inspect_response(body, effective, r.get('http_status'), r.get('exit_code'), kind)
            rows.append(dict(filename=name, request=r['request'], effective_url=effective, http_status=r.get('http_status'), exit_code=r.get('exit_code'),
                size_bytes=r.get('size_bytes'), sha256=r.get('sha256'), request_started_at=r['request_started_at'], observed_at=r['observed_at'],
                stderr=r.get('stderr', ''), error=r.get('error'), inspection=details))
    name = 'source_receipt.json' if TAG == 'sources' else TAG + '_source_receipt.json'
    atomic_json(OUT / name, dict(archive_sha256=pkg['sha256'], manifest_files=pkg['manifest_files'],
        roundtrip_verified=True, crc_manifest_verified=True, backup=transfer, observations=rows,
        source_gate_passed=False, historical_population_verified=False, original_publication_versions_verified=False,
        market_outcomes_inspected=False, meaning='Captured pages establish interface observations only. No case completeness or historical timing proof.'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['acquire', 'package', 'inspect'])
    parser.add_argument('--batch', choices=['sources', 'discovery', 'query', 'originals'], default='sources')
    args = parser.parse_args()
    TAG = args.batch
    if TAG != 'sources':
        REQUESTS = Path('configs/buyback_originals_sources_20261020.json') if TAG == 'originals' else Path('configs/buyback_preflight_' + TAG + '_sources_20261020.json')
    globals()[args.stage]()
