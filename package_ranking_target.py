"""Roundtrip checkpoint of this study's own matrices, six estimators and results."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from ranking_target_research import CONFIG, OUT, LOCAL
from research_runtime import atomic_json, sha256, utcnow


def run():
    state = json.loads((OUT/'pipeline/state.json').read_text())
    if state['status'] != 'complete':
        raise ValueError('Incomplete pipeline')
    for stage in state['stages'].values():
        if stage['status'] != 'complete':
            raise ValueError('Incomplete stage')
        for path, digest in stage['outputs'].items():
            if sha256(path) != digest:
                raise ValueError('Stage output differs: '+path)
    audit = json.loads((OUT/'audit.json').read_text())
    tests = json.loads((OUT/'tests.json').read_text())
    if audit['status'] != 'passed' or not tests['passed']:
        raise ValueError('Audit/tests not passed')
    for path, digest in tests['code_sha256'].items():
        if sha256(path) != digest:
            raise ValueError('Tested code differs: '+path)
    paths = [CONFIG, Path('configs/ranking_target_pipeline.json'),
        Path('ranking_target_research.py'), Path('ranking_target_review.py'),
        Path('test_ranking_target.py'), Path('package_ranking_target.py'),
        Path('research_pipeline.py'), Path('research_runtime.py'),
        Path('research_reassessment.py'), Path('audit_institutional_increment.py'),
        Path('configs/medium_term_protocol.json'), Path('docs/RANKING_TARGET_EXPERIMENT_20261023.md'),
        OUT/'pipeline/state.json']
    paths += sorted(p for p in OUT.iterdir() if p.is_file() and p.name != 'checkpoint.json')
    paths += sorted(p for p in LOCAL.iterdir() if p.is_file() and not p.name.endswith('.zip'))
    paths = list(dict.fromkeys(paths))
    manifest = {str(p): sha256(p) for p in paths}
    archive = LOCAL/'ranking_target_checkpoint.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        for p in paths:
            z.write(p, str(p))
        z.writestr('SHA256MANIFEST.json', json.dumps(manifest, indent=2)+'\n')
    saved = LOCAL/'backup/ranking_target_checkpoint.zip'
    saved.parent.mkdir(parents=True, exist_ok=True)
    retrieved = LOCAL/'ranking_target_checkpoint.retrieved.zip'
    shutil.copyfile(archive, saved)
    shutil.copyfile(saved, retrieved)
    digest = sha256(archive)
    for p in [archive, saved, retrieved]:
        if sha256(p) != digest:
            raise ValueError('Checkpoint roundtrip SHA differs')
        with zipfile.ZipFile(p) as z:
            if z.testzip() is not None or len(set(z.namelist())) != len(manifest)+1 or len(z.namelist()) != len(manifest)+1:
                raise ValueError('CRC/member count failure')
            for name, value in manifest.items():
                if hashlib.sha256(z.read(name)).hexdigest() != value:
                    raise ValueError('Manifest failure: '+name)
    atomic_json(OUT/'checkpoint.json', dict(status='passed', created_at=utcnow(),
        archive=str(archive), saved=str(saved), retrieved=str(retrieved),
        bytes=archive.stat().st_size, sha256=digest, manifest_files=len(manifest),
        sha_crc_manifest_roundtrip_verified=True, estimators=6,
        storage='Persistent local original/backup/readback; same filesystem, not offsite',
        raw_price_archive='ref/institutional_twse_2023_repro_bundle.zip',
        raw_price_archive_sha256='2e2654a125e7b33ac284cd5796be151738101b2ecb88f8407fae0f99317c4e94'))


if __name__ == '__main__':
    run()
