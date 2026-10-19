"""One bounded, paced recovery batch after explicit public-source quota responses."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import threading
import time

from bounded_public_sources import validate_config
from research_runtime import atomic_json, exclusive_lock, sha256, utcnow


def quota_body(body):
    return any('查詢過量' in body.decode(enc, errors='replace') for enc in ['utf-8','big5'])


def acquire(path):
    cfg = json.loads(Path(path).read_text())
    root = validate_config(cfg)
    if len(cfg['requests']) > 29 or cfg['request_interval_seconds'] < 4:
        raise ValueError('Recovery requires at most29 requests and at least4 seconds between starts')
    root.mkdir(parents=True,exist_ok=True)
    scheduling = threading.Lock()
    stopped = threading.Event()
    last_start = [None]

    def winpath(p):
        return subprocess.check_output(['wslpath','-w',str(p.resolve())],text=True).strip()

    def fetch(item):
        dest = root/item['filename']
        meta = dest.with_name(dest.name+'.meta.json')
        headers = dest.with_name(dest.name+'.headers')
        if meta.exists():
            old = json.loads(meta.read_text())
            if old['request'] != item:
                raise ValueError('Cached recovery request differs')
            for p,key in [(dest,'sha256'),(headers,'headers_sha256')]:
                if key in old and (not p.exists() or sha256(p)!=old[key]):
                    raise ValueError('Cached recovery bytes differ')
            if old.get('quota_refusal') or old.get('exit_code') != 0:
                stopped.set()
            return old
        if dest.exists() or headers.exists():
            raise ValueError('Unrecorded recovery partial file')
        row = dict(request=item,request_started_at=utcnow(),transport='Paced Windows curl; two workers, shared schedule',http_status=None)
        with scheduling:
            if last_start[0] is not None:
                delay = cfg['request_interval_seconds']-(time.monotonic()-last_start[0])
                if delay>0:
                    time.sleep(delay)
            if stopped.is_set():
                row.update(exit_code=None,request_started_at=None,not_requested_reason='prior_source_or_transport_failure')
                atomic_json(meta,row)
                return row
            last_start[0] = time.monotonic()
            row['request_started_at'] = utcnow()
        cmd = ['/mnt/c/Windows/System32/curl.exe','--location','--proto','=https','--proto-redir','=https','--max-redirs','3','--max-time','30','--max-filesize','33554432','--user-agent','stock_win source feasibility (https://github.com/parameciumvance/stock_win)','--output',winpath(dest),'--dump-header',winpath(headers),'--write-out','%{json}',item['url']]
        try:
            p = subprocess.run(cmd,capture_output=True,timeout=40)
            row.update(exit_code=p.returncode,stderr=p.stderr.decode(errors='replace'))
            try:
                row['curl'] = json.loads(p.stdout)
                row['http_status'] = row['curl'].get('http_code')
            except (ValueError,UnicodeDecodeError):
                row['write_out'] = p.stdout.decode(errors='replace')
        except subprocess.TimeoutExpired as e:
            row.update(exit_code=None,error=dict(type='SubprocessTimeout',seconds=e.timeout))
            stopped.set()
        if dest.exists():
            body = dest.read_bytes()
            row.update(sha256=sha256(dest),size_bytes=len(body),quota_refusal=quota_body(body))
            if row['quota_refusal']:
                stopped.set()
        if row['http_status'] in [403,429] or row['exit_code'] != 0:
            stopped.set()
        if headers.exists():
            row['headers_sha256'] = sha256(headers)
        row['observed_at'] = utcnow()
        atomic_json(meta,row)
        print(json.dumps(dict(filename=dest.name,status=row['http_status'],bytes=row.get('size_bytes'),quota_refusal=row.get('quota_refusal'))),flush=True)
        return row

    with exclusive_lock(root.parent/'acquisition.lock'):
        # Set the resume stop flag before workers can issue a new request.
        for item in cfg['requests']:
            meta=root/(item['filename']+'.meta.json')
            if meta.exists():
                old=json.loads(meta.read_text())
                if old.get('quota_refusal') or old.get('exit_code') != 0:
                    stopped.set()
        with ThreadPoolExecutor(max_workers=2) as pool:
            records = list(pool.map(fetch,cfg['requests']))
        atomic_json(root/'results.json',dict(config_sha256=sha256(path),workers=2,request_interval_seconds=cfg['request_interval_seconds'],requests=records))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('config')
    acquire(p.parse_args().config)
