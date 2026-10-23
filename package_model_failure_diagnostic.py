"""Save and read back this bounded diagnostic, retaining bulk artifacts outside Git."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from model_failure_diagnostic import CONFIG, LOCAL, OUT, require_hashes
from research_runtime import atomic_json, sha256, utcnow


def run():
    state = json.loads((OUT/'pipeline/state.json').read_text())
    if state['status'] != 'complete':
        raise ValueError('Pipeline incomplete')
    for stage in state['stages'].values():
        if stage['status'] != 'complete':
            raise ValueError('Stage incomplete')
        require_hashes(stage['outputs'])
    tests = json.loads((OUT/'tests.json').read_text())
    if not tests['passed']:
        raise ValueError('Tests not passed')
    require_hashes(tests['tested_code_sha256'])
    files = [CONFIG, Path('configs/model_failure_diagnostic_pipeline.json'),
        Path('model_failure_diagnostic.py'), Path('test_model_failure_diagnostic.py'),
        Path(__file__).resolve().relative_to(Path.cwd()),
        Path('docs/MODEL_FAILURE_DIAGNOSTIC_20261023.md'), LOCAL/'selected_replay.csv.gz', OUT/'pipeline/state.json']
    files += sorted(p for p in OUT.iterdir() if p.is_file() and p.name != 'checkpoint.json')
    files = list(dict.fromkeys(files))
    manifest = {str(p): sha256(p) for p in files}
    target = LOCAL/'diagnostic_checkpoint.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for p in files:
            archive.write(p, str(p))
        archive.writestr('SHA256MANIFEST.json', json.dumps(manifest, indent=2)+'\n')
    saved = LOCAL/'backup/diagnostic_checkpoint.zip'
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target, saved)
    retrieved = LOCAL/'diagnostic_checkpoint.retrieved.zip'
    shutil.copyfile(saved, retrieved)
    for path in [target, saved, retrieved]:
        if sha256(path) != sha256(target):
            raise ValueError('Saved/readback archive differs')
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None or len(archive.namelist()) != len(manifest)+1:
                raise ValueError('CRC or member-count failure')
            for name, digest in manifest.items():
                if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                    raise ValueError('Manifest readback failure')
    atomic_json(OUT/'checkpoint.json', dict(status='passed', created_at=utcnow(),
        archive=str(target), backup=str(saved), retrieved=str(retrieved),
        sha256=sha256(target), manifest_files=len(manifest),
        sha_crc_manifest_roundtrip_verified=True,
        storage='Persistent local copies on same filesystem, not offsite',
        source_archive_sha256=json.loads((OUT/'source_receipt.json').read_text())['archive_sha256']))


if __name__ == '__main__':
    run()
