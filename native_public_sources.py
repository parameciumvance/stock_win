"""Bounded WSL-native curl acquisition, separate from frozen Windows acquisition code."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

from bounded_public_sources import validate_config
from research_runtime import atomic_json,exclusive_lock,sha256,utcnow


def acquire(config):
    config=Path(config);cfg=json.loads(config.read_text());root=validate_config(cfg);root.mkdir(parents=True,exist_ok=True)
    def fetch(item):
        path=root/item['filename'];meta=path.with_name(path.name+'.meta.json');headers=path.with_name(path.name+'.headers')
        if meta.exists():
            old=json.loads(meta.read_text())
            if old.get('request')!=item or old.get('transport')!='WSL native curl; verified HTTPS; two workers':raise ValueError('Cached request/transport drift')
            for file,key in [(path,'sha256'),(headers,'headers_sha256')]:
                if key in old and (not file.exists() or sha256(file)!=old[key]):raise ValueError('Cached source drift')
                if key not in old and file.exists():raise ValueError('Unrecorded partial source')
            return old
        if path.exists() or headers.exists():raise ValueError('Unrecorded partial acquisition; do not overwrite')
        command=['curl','--location','--proto','=https','--proto-redir','=https','--max-redirs','3','--max-time','30','--max-filesize','33554432','--retry','0','--user-agent','stock_win research (https://github.com/parameciumvance/stock_win)','--output',str(path),'--dump-header',str(headers),'--write-out','%{json}']
        if item.get('method')=='POST':command+=['--data',item.get('data','')]
        command+=[item['url']]
        row=dict(request=item,request_started_at=utcnow(),transport='WSL native curl; verified HTTPS; two workers',http_status=None)
        try:
            result=subprocess.run(command,capture_output=True,timeout=40)
            row.update(exit_code=result.returncode,stderr=result.stderr.decode(errors='replace'))
            try:
                row['curl']=json.loads(result.stdout);row['http_status']=row['curl'].get('http_code')
            except (ValueError,UnicodeDecodeError):row['write_out']=result.stdout.decode(errors='replace')
        except subprocess.TimeoutExpired as error:row.update(exit_code=None,error=dict(type='SubprocessTimeout',seconds=error.timeout))
        if path.exists():row.update(sha256=sha256(path),size_bytes=path.stat().st_size)
        if headers.exists():row['headers_sha256']=sha256(headers)
        row['observed_at']=utcnow();atomic_json(meta,row)
        print(json.dumps(dict(filename=path.name,http_status=row['http_status'],exit_code=row.get('exit_code'),bytes=row.get('size_bytes'))),flush=True)
        return row
    with exclusive_lock(root.parent/'acquisition.lock'):
        with ThreadPoolExecutor(max_workers=2) as pool:records=list(pool.map(fetch,cfg['requests']))
        atomic_json(root/'results.json',dict(config_sha256=sha256(config),workers=2,requests=records))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('config');acquire(parser.parse_args().config)
