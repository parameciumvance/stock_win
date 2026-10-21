"""Bounded byte acquisition and immutable source checkpoints; no semantic claims."""
import argparse
import json
from pathlib import Path
import re
import zipfile

from bounded_public_sources import validate_config
from native_public_sources import acquire as native_acquire
from research_runtime import atomic_bytes, atomic_json, exclusive_lock, sha256
from source_checkpoint import package_sources, readback
from tender_preflight import verified_records

ROOT = Path('inputs/frontier_20261020')
OUT = Path('deliverables/frontier_20261020')
POLICY = Path('configs/research_frontier_protocol_20261020.json')


def read(path):
    return json.loads(Path(path).read_text())


def plan(batch):
    if not isinstance(batch, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', batch):
        raise ValueError('Unsafe batch name')
    digest = sha256(POLICY)
    if digest != read(OUT / 'protocol_freeze.json')['protocol_sha256']:
        raise ValueError('Frozen frontier protocol drift')
    policy = read(POLICY)
    for path, expected in policy['prior_checkpoints'].items():
        if sha256(path) != expected:
            raise ValueError('Prior checkpoint drift: ' + path)
        for member, value in read(path)['files'].items():
            if sha256(member) != value:
                raise ValueError('Prior checkpoint member drift: ' + member)
    batches, freezes = dict(policy['batches']), {}
    for path in OUT.glob('*_freeze.json'):
        if path.name == 'protocol_freeze.json':
            continue
        name, value = path.name.removesuffix('_freeze.json'), read(path)
        if name in batches or value.get('protocol_sha256') != digest:
            raise ValueError('Conflicting or stale adaptive batch freeze')
        batches[name], freezes[name] = value, path
    counts = [value['requests'] for value in batches.values()]
    limit = policy['max_saved_requests']
    batch_limit = policy.get('max_source_batches', 4)
    if (type(limit) is not int or limit < 1 or any(type(n) is not int or n < 1 for n in counts)
            or type(batch_limit) is not int or batch_limit < 1 or len(batches) > batch_limit
            or sum(counts) > limit or batch not in batches):
        raise ValueError('Unknown batch or saved-request budget exceeded')
    for value in batches.values():
        if sha256(value['path']) != value['sha256'] or len(read(value['path'])['requests']) != value['requests']:
            raise ValueError('Frozen request configuration drift')
    requests = Path(batches[batch]['path'])
    cfg = read(requests)
    raw = validate_config(cfg)
    if raw.parent != ROOT or raw == ROOT:
        raise ValueError('Raw directory must share frontier acquisition lock')
    return requests, cfg, raw, freezes.get(batch)


def cached(requests, cfg, raw):
    """Check every cached leg before native workers may make any live request."""
    for item in cfg['requests']:
        name = item['filename']
        meta = raw / (name + '.meta.json')
        if meta.exists():
            record = read(meta)
            if record.get('request') != item or record.get('transport') != 'WSL native curl; verified HTTPS; two workers':
                raise ValueError('Cached request/transport drift')
            for suffix, key in [('', 'sha256'), ('.headers', 'headers_sha256')]:
                path = raw / (name + suffix)
                if ((key in record and (not path.exists() or sha256(path) != record[key]))
                        or (key not in record and path.exists())):
                    raise ValueError('Cached source drift: ' + name + suffix)
        elif any((raw / (name + suffix)).exists() for suffix in ('', '.headers')):
            raise ValueError('Unrecorded partial source; not overwritten')
    if (raw / 'results.json').exists():
        results = read(raw / 'results.json')
        if results['config_sha256'] != sha256(requests):
            raise ValueError('Cached result configuration drift')
        verified_records(cfg, results, lambda name: (raw / name).read_bytes())


def archived(batch, requests, freeze):
    package, transfer = readback(OUT, batch)
    with zipfile.ZipFile(package['retrieved']) as archive:
        for name, path in [('protocol.json', POLICY), ('requests.json', requests)] + (
                [('batch_freeze.json', freeze)] if freeze else []):
            if archive.read(name) != Path(path).read_bytes():
                raise ValueError('Archived frozen policy/request drift')
    return package, transfer


def acquire(batch='discovery'):
    requests, cfg, raw, freeze = plan(batch)
    if (OUT / (batch + '_package.json')).exists():
        package, _ = archived(batch, requests, freeze)
        with exclusive_lock(ROOT / 'acquisition.lock'), zipfile.ZipFile(package['retrieved']) as archive:
            for member in archive.namelist():
                if not member.startswith('raw/'):
                    continue
                name, body = member[4:], archive.read(member)
                if not name or Path(name).name != name:
                    raise ValueError('Unsafe archived raw path')
                dest = raw / name
                if dest.exists() and dest.read_bytes() != body:
                    raise ValueError('Saved local source differs; not overwritten: ' + name)
                if not dest.exists():
                    atomic_bytes(dest, body)
            cached(requests, cfg, raw)
        return
    cached(requests, cfg, raw)
    if (raw / 'results.json').exists():
        return
    native_acquire(requests)  # Native owns ROOT/acquisition.lock; no nested lock.


def package(batch='discovery'):
    requests, cfg, raw, freeze = plan(batch)
    cached(requests, cfg, raw)
    if not (raw / 'results.json').exists():
        raise ValueError('No complete acquisition result to package')
    entries = {'protocol.json': POLICY, 'requests.json': requests}
    if freeze:
        entries['batch_freeze.json'] = freeze
    entries.update({'raw/' + p.name: p for p in raw.iterdir() if p.is_file()})
    with exclusive_lock(ROOT / 'acquisition.lock'):
        if (OUT / (batch + '_package.json')).exists():
            previous, _ = archived(batch, requests, freeze)
            with zipfile.ZipFile(previous['retrieved']) as archive:
                if {name: sha256(path) for name, path in entries.items()} != json.loads(archive.read('manifest.json')):
                    raise ValueError('Frozen source package differs; not replaced')
            return
        package_sources(ROOT, OUT, batch, entries)


def verify(batch='discovery'):
    requests, cfg, _, freeze = plan(batch)
    package, transfer = archived(batch, requests, freeze)
    with zipfile.ZipFile(package['retrieved']) as archive:
        results = json.loads(archive.read('raw/results.json'))
        if results['config_sha256'] != sha256(requests):
            raise ValueError('Archived result configuration drift')
        records = verified_records(cfg, results, lambda name: archive.read('raw/' + name))
    atomic_json(OUT / ('source_receipt_' + batch + '.json'), dict(
        archive_sha256=package['sha256'], manifest_files=package['manifest_files'],
        roundtrip_verified=True, crc_manifest_verified=True, backup=transfer,
        observations=records, semantic_source_validated=False, historical_pit_verified=False,
        complete_population_verified=False, source_gate_passed=False,
        meaning='Verified saved bytes and actual transport observations only; failed HTTP responses remain evidence.'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['acquire', 'package', 'verify'])
    parser.add_argument('--batch', default='discovery')
    arguments = parser.parse_args()
    globals()[arguments.stage](arguments.batch)
