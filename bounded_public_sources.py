"""Two-worker, locked, bounded Windows-curl acquisition of public research files."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from research_runtime import atomic_json,exclusive_lock,sha256,utcnow


def validate_config(cfg):
    root=Path(cfg['output_directory'])
    if root.is_absolute() or '..' in root.parts or not str(root).startswith('inputs/'):
        raise ValueError('Output must be under ignored project inputs')
    items=cfg['requests'];names=[]
    if not 1<=len(items)<=30:raise ValueError('Bounded batch size must be 1..30')
    for item in items:
        name=item['filename'];parts=urlsplit(item['url'])
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or name in {'.','..'}:raise ValueError('Unsafe filename')
        if parts.scheme!='https' or parts.username or parts.password or parts.hostname not in cfg['allowed_hosts']:
            raise ValueError('Source outside declared public HTTPS hosts')
        if item.get('method','GET') not in {'GET','POST'}:raise ValueError('Unsupported method')
        names.append(name)
    if len(set(names))!=len(names):raise ValueError('Duplicate output filename')
    return root


def acquire(config):
    config=Path(config);cfg=json.loads(config.read_text());root=validate_config(cfg);root.mkdir(parents=True,exist_ok=True)
    def winpath(p):return subprocess.check_output(['wslpath','-w',str(p.resolve())],text=True).strip()
    def fetch(item):
        name=item['filename'];dest=root/name;meta=root/(name+'.meta.json');headers=root/(name+'.headers')
        if meta.exists():
            old=json.loads(meta.read_text())
            if old.get('request')!=item:raise ValueError('Existing request differs')
            if 'sha256' in old and (not dest.exists() or sha256(dest)!=old['sha256']):raise ValueError('Cached response drift')
            if 'sha256' not in old and dest.exists():raise ValueError('Unrecorded cached partial response')
            if 'headers_sha256' in old and sha256(headers)!=old['headers_sha256']:raise ValueError('Cached headers drift')
            return old
        if dest.exists() or headers.exists():raise ValueError('Partial acquisition needs explicit recovery; no silent overwrite')
        cmd=['/mnt/c/Windows/System32/curl.exe','--location','--proto','=https','--proto-redir','=https','--max-redirs','3','--max-time','30','--max-filesize','33554432','--user-agent','stock_win source feasibility (https://github.com/parameciumvance/stock_win)','--output',winpath(dest),'--dump-header',winpath(headers),'--write-out','%{json}']
        if item.get('method')=='POST':cmd+=['--data',item.get('data','')]
        cmd+=[item['url']]
        row=dict(request=item,request_started_at=utcnow(),transport='Windows curl.exe via WSL; two workers',http_status=None)
        try:
            p=subprocess.run(cmd,capture_output=True,timeout=40)
            row.update(exit_code=p.returncode,stderr=p.stderr.decode(errors='replace'))
            try:row['curl']=json.loads(p.stdout);row['http_status']=row['curl'].get('http_code')
            except (ValueError,UnicodeDecodeError):row['write_out']=p.stdout.decode(errors='replace')
        except subprocess.TimeoutExpired as e:
            row.update(error=dict(type='SubprocessTimeout',seconds=e.timeout),exit_code=None)
        if dest.exists():row.update(sha256=sha256(dest),size_bytes=dest.stat().st_size)
        if headers.exists():row['headers_sha256']=sha256(headers)
        row['observed_at']=utcnow();atomic_json(meta,row)
        print(json.dumps(dict(filename=name,status=row['http_status'],bytes=row.get('size_bytes'),error=row.get('error'))),flush=True)
        return row
    with exclusive_lock(root.parent/'acquisition.lock'):
        with ThreadPoolExecutor(max_workers=2) as pool:records=list(pool.map(fetch,cfg['requests']))
        atomic_json(root/'results.json',dict(config_sha256=sha256(config),workers=2,requests=records))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('config');acquire(p.parse_args().config)
