"""Close and validate the early-revenue source archive before publication."""
import hashlib,json,zipfile
from pathlib import Path

def main():
 root=Path('deliverables/tpex_revenue_2016_202210')
 if json.loads((root/'source_health.json').read_text())['raw_replay_equal'] is not True:raise ValueError('Raw replay required')
 paths=[p for d in ['tpex_revenue_2015_pilot','tpex_revenue_2016_202210'] for p in (Path('deliverables')/d/'raw').iterdir() if p.suffix in ['.html','.json']]
 paths += [Path('deliverables')/d/n for d in ['tpex_revenue_2015_pilot','tpex_revenue_2016_202210'] for n in ['monthly.csv.gz','acquisition.json','source_health.json']]
 paths += [Path(n) for n in ['acquire_tpex_revenue.py','audit_tpex_revenue_archive.py','package_tpex_early_revenue.py','research_runtime.py','research_pipeline.py','test_tpex_revenue.py','test_tpex_revenue_bounds.py','tests/fixtures/tpex_revenue_202301_0.html.gz','configs/tpex_early_revenue_extension.json','configs/tpex_event_rules_protocol.json']]
 manifest={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
 out=root/'tpex_revenue_2014_202210_source_checkpoint.zip';pending=out.with_suffix('.pending.zip')
 with zipfile.ZipFile(pending,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in sorted(paths):z.write(p,str(p))
  z.writestr('SHA256MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
 with zipfile.ZipFile(pending) as z:
  if z.testzip() is not None:raise ValueError('CRC failure')
  if set(z.namelist())!=set(manifest)|{'SHA256MANIFEST.json'}:raise ValueError('Member set differs')
  for name,digest in manifest.items():
   if hashlib.sha256(z.read(name)).hexdigest()!=digest:raise ValueError('Archive member mismatch')
 pending.replace(out)
 metadata=dict(sha256=hashlib.sha256(out.read_bytes()).hexdigest(),bytes=out.stat().st_size,manifest_files=len(manifest),archive=str(out),scope='2014-11 through 2022-10 raw retrospective TPEx revenue sources and offline replay')
 (root/'source_checkpoint.json').write_text(json.dumps(metadata,indent=2)+'\n');print(json.dumps(metadata))

if __name__=='__main__':main()
