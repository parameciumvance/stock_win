"""Immutable observation journal; deliberately has no download or trade service."""
import argparse
import hashlib
import json
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Taipei')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def seal(root, kind, key, payload, *, now=None):
    explicit_clock = now is not None
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        raise ValueError('Timezone-aware clock required')
    now = now.astimezone(TZ)
    if kind not in ('snapshot', 'signal'):
        raise ValueError('Unknown record kind')
    if not key or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in key):
        raise ValueError('Unsafe record key')
    if kind == 'signal':
        signal_date = date.fromisoformat(payload['signal_date'])
        if signal_date < date(2026, 10, 14) or signal_date != now.date():
            raise ValueError('No backdated or future signal sealing')
        if now.hour < 15:
            raise ValueError('Seal after daily source cutoff, 15:00 Taipei')
        if payload.get('status') not in ('complete', 'missing_inputs', 'insufficient_pool'):
            raise ValueError('Explicit signal status required')
        if key != signal_date.isoformat():
            raise ValueError('One signal record per market date')
        if not payload.get('protocol_sha256') or len(payload['protocol_sha256']) != 64 or any(c not in '0123456789abcdef' for c in payload['protocol_sha256']):
            raise ValueError('Protocol digest required')
        if payload['status'] == 'complete' and not payload.get('snapshot_records'):
            raise ValueError('Complete signal requires prior snapshots')
        if payload['status'] == 'complete' and payload.get('source_status') != 'raw_replay_verified':
            raise ValueError('Complete signal requires raw-source replay gate')
        if payload['status'] == 'complete' and (not payload.get('selection_manifest_sha256') or len(payload['selection_manifest_sha256']) != 64):
            raise ValueError('Complete signal requires selection manifest digest')
        for ref in payload.get('snapshot_records', []):
            if not ref or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in ref):
                raise ValueError('Unsafe snapshot reference')
            record = verify(Path(root) / 'snapshot' / (ref + '.json'))
            if datetime.fromisoformat(record['observed_at']) > now:
                raise ValueError('Snapshot observed after signal')
    if kind == 'signal' and payload['status'] == 'complete':
        from prospective_replay import validate_live_payload
        validate_live_payload(root, payload, now)
        if not explicit_clock:
            now = datetime.now(TZ)
            if now.date() != signal_date or now >= datetime.fromisoformat(payload['entry_at']):
                raise ValueError('Replay completed after signal/entry deadline')
    record = {'kind': kind, 'key': key, 'observed_at': now.isoformat(), 'payload': payload}
    encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    envelope = {'record': record, 'record_sha256': sha(encoded)}
    target = Path(root) / kind / (key + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects already sealed decisions from revisions.
    with target.open('x', encoding='utf-8') as stream:
        json.dump(envelope, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')
    return target

def verify(path):
    envelope = json.loads(Path(path).read_text())
    record = envelope['record']
    encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    if sha(encoded) != envelope['record_sha256']:
        raise ValueError('Journal digest mismatch')
    return record

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['snapshot', 'signal', 'verify'])
    parser.add_argument('file', type=Path)
    parser.add_argument('--root', type=Path, default=Path('deliverables/prospective_journal'))
    parser.add_argument('--key')
    args = parser.parse_args()
    if args.kind == 'verify':
        print(json.dumps(verify(args.file), ensure_ascii=False)); return
    if not args.key:
        parser.error('--key required')
    if args.kind == 'snapshot':
        raw = args.file.read_bytes()
        digest = sha(raw)
        raw_root = args.root / 'raw'; raw_root.mkdir(parents=True, exist_ok=True)
        raw_path = raw_root / digest
        if raw_path.exists():
            if sha(raw_path.read_bytes()) != digest:
                raise ValueError('Stored raw digest mismatch')
        else:
            with raw_path.open('xb') as stream: stream.write(raw)
        payload = {'raw_sha256': digest, 'size_bytes': len(raw), 'source_filename': args.file.name}
    else:
        payload = json.loads(args.file.read_text())
    print(seal(args.root, args.kind, args.key, payload))

if __name__ == '__main__':
    main()
