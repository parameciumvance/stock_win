"""Restartable serial stage runner; completion is hash-verified, never inferred from a PID."""
import argparse,contextlib,gzip,json,os,signal,subprocess,sys,time,zipfile
from pathlib import Path
from research_runtime import atomic_json,exclusive_lock,process_identity,rss_bytes,runtime_probe,sha256,utcnow

class NeedsRestore(Exception):pass
class NeedsCheckpoint(Exception):pass

def files_for(patterns):
 files=[]
 for pattern in patterns:
  matches=sorted(Path('.').glob(pattern)) if not Path(pattern).is_absolute() else [Path(pattern)]
  expanded=[]
  for p in matches:
   expanded.extend(sorted(q for q in p.rglob('*') if q.is_file())) if p.is_dir() else expanded.append(p)
  expanded=[p for p in expanded if p.is_file() and not p.name.endswith('.pending')]
  if not expanded:raise NeedsRestore('Missing input/output: '+pattern)
  files.extend(expanded)
 return list(dict.fromkeys(files))

def hashes(patterns,validate=False):
 result={}
 for path in files_for(patterns):
  if validate:
   if path.suffix=='.json':json.loads(path.read_text())
   elif path.suffix=='.gz':
    with gzip.open(path,'rb') as f:
     for _ in iter(lambda:f.read(1024*1024),b''):pass
   elif path.suffix=='.zip':
    with zipfile.ZipFile(path) as z:
     if z.testzip() is not None:raise ValueError('Archive CRC failure: '+str(path))
  result[str(path)]=sha256(path)
 return result

def fingerprint(stage,command):
 import hashlib
 return hashlib.sha256(json.dumps(dict(stage=stage,command=command,inputs=hashes(stage.get('inputs',[]))),sort_keys=True).encode()).hexdigest()

def durable_checkpoint(stage):
 archive=Path(stage['checkpoint']['archive']);receipt=Path(stage['checkpoint']['receipt'])
 if not archive.is_file() or not receipt.is_file():raise NeedsCheckpoint('Save and read back '+str(archive)+'; receipt: '+str(receipt))
 r=json.loads(receipt.read_text())
 if not r.get('library_file_id') or r.get('roundtrip_verified') is not True or r.get('sha256')!=sha256(archive):raise NeedsCheckpoint('Checkpoint receipt is absent, stale, or not roundtrip verified: '+str(receipt))
 return {str(archive):r['sha256'],str(receipt):sha256(receipt)}

def stop_child(child):
 if child.poll() is not None:return
 with contextlib.suppress(ProcessLookupError):os.killpg(child.pid,signal.SIGTERM)
 try:child.wait(timeout=5)
 except subprocess.TimeoutExpired:
  with contextlib.suppress(ProcessLookupError):os.killpg(child.pid,signal.SIGKILL)
  child.wait()

def run(plan,state_dir,code_commit='',heartbeat=15,poll=.5):
 state_dir=Path(state_dir);state_dir.mkdir(parents=True,exist_ok=True);state_file=state_dir/'state.json';logs=state_dir/'logs';logs.mkdir(exist_ok=True)
 if heartbeat<=0 or poll<=0:raise ValueError('Heartbeat and poll must be positive')
 ids=[s['id'] for s in plan['stages']]
 if len(ids)!=len(set(ids)) or any(not i or '/' in i or '\\' in i or i in ['.','..'] for i in ids):raise ValueError('Invalid or duplicate stage ID')
 with exclusive_lock(state_dir/'run.lock'):
  state=json.loads(state_file.read_text()) if state_file.exists() else dict(stages={})
  probe=runtime_probe();old=state.get('active',{})
  if state.get('runtime_identity')==probe['runtime_identity'] and old.get('pid') and process_identity(old['pid'])==old.get('process_identity') and old.get('process_identity') is not None:
   state['status']='orphan_running';state['message']='Prior child is still alive; no duplicate job started';atomic_json(state_file,state);return 75
  if state.get('status')=='running':state.setdefault('interruptions',[]).append(dict(observed_at=utcnow(),previous_active=old))
  state.update(status='running',started_at=utcnow(),runtime_identity=probe['runtime_identity'],active={})
  def save():state['heartbeat_at']=utcnow();atomic_json(state_file,state)
  save()
  for stage in plan['stages']:
   sid=stage['id'];state['current_stage']=sid;child=None;record={};log_path=None
   try:
    command=[str(v).replace('{python}',sys.executable).replace('{code_commit}',code_commit) for v in stage.get('command',[])]
    if any(not v for v in command) or ('{code_commit}' in json.dumps(stage) and not code_commit):raise ValueError('Provide --code-commit for packaging')
    key=fingerprint(stage,command);previous=state['stages'].get(sid,{})
    if previous.get('status')=='complete' and previous.get('fingerprint')==key:
     try:
      current=durable_checkpoint(stage) if 'checkpoint' in stage else hashes(stage.get('outputs',[]),validate=True)
      if current==previous.get('outputs'):print('verified skip:',sid,flush=True);continue
     except (NeedsCheckpoint,NeedsRestore,ValueError,EOFError,OSError):pass
    record=dict(status='running',fingerprint=key,started_at=utcnow(),runtime_before=runtime_probe());state['stages'][sid]=record;save()
    if 'checkpoint' in stage:
     record['outputs']=durable_checkpoint(stage)
    else:
     if not command:raise ValueError('Stage needs a command or checkpoint')
     timeout=float(stage.get('timeout_seconds',plan.get('timeout_seconds',3600)));limit=int(stage.get('max_rss_mb',plan.get('max_rss_mb',0)))*1024*1024
     if timeout<=0 or limit<0:raise ValueError('Invalid time/resource limit')
     attempts=int(stage.get('attempts',1));retry_codes=stage.get('retry_exit_codes',[])
     if not 1<=attempts<=3:raise ValueError('Attempts must be 1..3')
     for attempt in range(1,attempts+1):
      log_path=logs/f'{sid}.{time.time_ns()}.log';record.update(attempt=attempt,log=str(log_path),peak_observed_rss_bytes=0);started=time.monotonic();last=started
      with log_path.open('ab',buffering=0) as log:
       child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'PYTHONUNBUFFERED':'1'})
       state['active']=dict(stage=sid,pid=child.pid,process_identity=process_identity(child.pid));save()
       while child.poll() is None:
        elapsed=time.monotonic()-started;rss=rss_bytes(child.pid);record['peak_observed_rss_bytes']=max(record['peak_observed_rss_bytes'],rss or 0)
        if elapsed>timeout or (limit and rss is not None and rss>limit):
         record['failure_reason']='timeout' if elapsed>timeout else 'memory_guard';stop_child(child);break
        if time.monotonic()-last>=heartbeat:
         record['elapsed_seconds']=elapsed
         if stage.get('progress'):
          try:record['source_progress']=json.loads(Path(stage['progress']).read_text())
          except (OSError,ValueError):pass
         save();print('heartbeat:',sid,'elapsed',round(elapsed),'seconds; log',log_path,flush=True);last=time.monotonic()
        time.sleep(poll)
       record['exit_code']=child.wait();record['exit_signal']=-record['exit_code'] if record['exit_code']<0 else None;record['elapsed_seconds']=time.monotonic()-started;state['active']={};save()
      if record.get('failure_reason') or record['exit_code'] not in retry_codes or attempt==attempts:break
      time.sleep(min(attempt,3))
     if record.get('failure_reason') or record['exit_code']!=0:raise RuntimeError('Child failed; inspect '+str(log_path))
     record['outputs']=hashes(stage.get('outputs',[]),validate=True)
    record.update(status='complete',finished_at=utcnow(),runtime_after=runtime_probe());save();print('complete:',sid,flush=True)
   except (NeedsCheckpoint,NeedsRestore) as e:
    record.update(status='awaiting_checkpoint' if isinstance(e,NeedsCheckpoint) else 'needs_restore',message=str(e));state['stages'][sid]=record;state.update(status=record['status'],message=str(e),active={});save();print(str(e),flush=True);return 78
   except KeyboardInterrupt:
    if child:stop_child(child)
    record.update(status='interrupted',runtime_after=runtime_probe());state['stages'][sid]=record;state.update(status='interrupted',active={});save();return 130
   except Exception as e:
    if child:stop_child(child)
    record.update(status='failed',error=type(e).__name__+': '+str(e),runtime_after=runtime_probe());state['stages'][sid]=record;state.update(status='failed',active={},message=record['error']);save();print(record['error'],flush=True);return 1
  state.update(status='complete',finished_at=utcnow(),active={});save();return 0

def main():
 p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--state-dir',default='deliverables/research_run');p.add_argument('--code-commit',default='');p.add_argument('--heartbeat-seconds',type=float,default=15);p.add_argument('--status',action='store_true');a=p.parse_args()
 if a.status:
  state=Path(a.state_dir)/'state.json';print(state.read_text() if state.exists() else json.dumps({'status':'not_started'}));return 0
 def terminated(signum,frame):raise KeyboardInterrupt
 signal.signal(signal.SIGTERM,terminated)
 return run(json.loads(Path(a.plan).read_text()),a.state_dir,a.code_commit,a.heartbeat_seconds)
if __name__=='__main__':sys.exit(main())
