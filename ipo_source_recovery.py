"""Preserve one predeclared source discrepancy recovery; no source is silently replaced."""
import json
from pathlib import Path
from research_runtime import exclusive_lock, sha256
from source_checkpoint import package_sources
from tender_preflight import verified_records

def package():
    root=Path('inputs/ipo_replication_20261020');out=Path('deliverables/ipo_replication_20261020')
    protocol=Path('configs/ipo_replication_recovery_protocol_20261020.json');requests=Path('configs/ipo_replication_recovery_sources.json')
    p=json.loads(protocol.read_text());freeze=json.loads((out/'source_recovery_freeze.json').read_text());cfg=json.loads(requests.read_text())
    if sha256(protocol)!=freeze['protocol_sha256'] or sha256(requests)!=p['source_requests_sha256'] or len(cfg['requests'])>p['max_requests']:
        raise ValueError('Recovery freeze or request budget differs')
    raw=root/'raw_recovery';result=json.loads((raw/'results.json').read_text())
    if result['config_sha256']!=sha256(requests):raise ValueError('Recovery source request drift')
    verified_records(cfg,result,lambda name:(raw/name).read_bytes())
    entries={'recovery_protocol.json':protocol,'requests.json':requests}
    entries.update({'raw/'+path.name:path for path in raw.iterdir() if path.is_file()})
    with exclusive_lock(root/'acquisition.lock'):package_sources(root,out,'recovery',entries)

if __name__=='__main__':package()
