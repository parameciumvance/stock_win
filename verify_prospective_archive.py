"""Read-only regression of a sealed signal using current replay code and original bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd

from prospective_journal import verify
from prospective_replay import frozen, rebuild, independent_selection
from prospective_sources import verify_archive
from research_runtime import atomic_json, sha256, utcnow


def audit(root, out, sealed_code_commit):
    protocol=frozen()
    before={str(p):sha256(p) for p in root.rglob('*') if p.is_file() and 'benchmark_replay' not in p.parts and 'pipeline' not in p.parts and not p.name.endswith('.log')}
    for name in ('checkpoint.json','signal_checkpoint.json'):
        checkpoint=json.loads((root/name).read_text())
        verify_archive(Path(checkpoint['retrieved_path']),checkpoint['sha256'])
        if sha256(checkpoint['backup_path'])!=checkpoint['sha256']:
            raise ValueError('Sealed backup mismatch')
    original=json.loads((root/'selection_manifest.json').read_text())
    for path, expected in original['code_sha256'].items():
        body=subprocess.check_output(['git','show',f'{sealed_code_commit}:{path}'])
        if hashlib.sha256(body).hexdigest()!=expected:
            raise ValueError('Original sealed code not recovered: '+path)
    signal=verify(root/'journal/signal'/f'{original["summary"]["signal_date"]}.json')
    if signal['payload']['selection_manifest_sha256']!=sha256(root/'selection_manifest.json'):
        raise ValueError('Sealed manifest mismatch')
    matrices, summary, benchmark=rebuild(root,scratch_root=root.parent/'audit_scratch'/out.name)
    if summary!=original['summary']:
        raise ValueError('Current replay changed original summary')
    for lag, frame in matrices.items():
        saved=pd.read_csv(root/f'matrix_{lag}.csv',dtype={'code':str,'date':str},float_precision='round_trip')
        pd.testing.assert_frame_equal(saved,frame,check_dtype=False,check_exact=False,rtol=1e-14,atol=1e-14)
        if independent_selection(frame,summary['signal_date'])!=original['results'][lag]:
            raise ValueError('Current replay changed sealed selection')
    if benchmark.to_csv(index=False,float_format='%.17g').encode()!=(root/'benchmark.csv').read_bytes():
        raise ValueError('Current replay changed benchmark')
    if any(sha256(path)!=digest for path,digest in before.items()):
        raise ValueError('Read-only audit modified original evidence')
    atomic_json(out/'sealed_regression.json',dict(status='passed',observed_at=utcnow(),signal_date=summary['signal_date'],sealed_at=signal['observed_at'],sealed_code_commit=sealed_code_commit,protocol_sha256=sha256('configs/tpex_prospective_protocol.json'),frozen_blobs=protocol['frozen_source_git_blobs'],source_archive_sha256=summary['archive_sha256'],original_manifest_sha256=sha256(root/'selection_manifest.json'),original_files_verified_unchanged=len(before),matrices_replayed=list(matrices),same_pool=original['results']['45']['common_pool'],all_selections_identical=True,benchmark_identical=True,current_code_sha256={p:sha256(p) for p in ('prospective_sources.py','prospective_replay.py','verify_prospective_archive.py')}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--sealed-code-commit',required=True);a=p.parse_args();audit(a.root,a.out,a.sealed_code_commit)
