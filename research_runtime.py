"""Small POSIX/WSL durability and diagnostics utilities for research jobs."""
import contextlib,datetime,fcntl,hashlib,json,os,socket,tempfile
from pathlib import Path

def utcnow():
 return datetime.datetime.now(datetime.timezone.utc).isoformat()

def sha256(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def atomic_bytes(path,payload):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.pending',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
  os.replace(name,path)
  directory=os.open(path.parent,os.O_RDONLY)
  try:os.fsync(directory)
  finally:os.close(directory)
 finally:
  with contextlib.suppress(FileNotFoundError):os.unlink(name)

def atomic_json(path,value):
 atomic_bytes(path,(json.dumps(value,indent=2,allow_nan=False)+'\n').encode())

@contextlib.contextmanager
def exclusive_lock(path):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('a+') as f:
  try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise RuntimeError('Another writer owns '+str(path))
  try:yield
  finally:fcntl.flock(f,fcntl.LOCK_UN)

def runtime_probe():
 def read(path):
  try:return Path(path).read_text().strip()
  except OSError:return None
 boot=read('/proc/sys/kernel/random/boot_id') or 'unknown'
 namespace=os.readlink('/proc/self/ns/pid')
 identity=hashlib.sha256((boot+'|'+socket.gethostname()+'|'+namespace).encode()).hexdigest()
 events=read('/sys/fs/cgroup/memory.events')
 return dict(observed_at=utcnow(),runtime_identity=identity,
  memory_events={k:int(v) for k,v in (line.split() for line in events.splitlines())} if events else None,
  memory_current_bytes=read('/sys/fs/cgroup/memory.current'),memory_limit_bytes=read('/sys/fs/cgroup/memory.max'))

def process_directory(pid):
 """Resolve process IDs when a sandbox exposes the host /proc mount."""
 namespace=os.readlink('/proc/self/ns/pid')
 own=Path('/proc/self/status').read_text()
 host_pid=int(next(line.split()[1] for line in own.splitlines() if line.startswith('Pid:')))
 if host_pid==os.getpid():return Path(f'/proc/{pid}')
 for path in Path('/proc').iterdir():
  if not path.name.isdigit():continue
  try:
   if os.readlink(path/'ns/pid')!=namespace:continue
   status=(path/'status').read_text()
   ids=next(line.split()[1:] for line in status.splitlines() if line.startswith('NSpid:'))
   if int(ids[-1])==pid:return path
  except (OSError,StopIteration,ValueError):continue
 raise ProcessLookupError(pid)

def process_identity(pid):
 try:
  os.kill(pid,0)
  fields=(process_directory(pid)/'stat').read_text().rsplit(')',1)[1].split()
  if fields[0]=='Z':return None
  return fields[19]
 except (OSError,IndexError):return None

def rss_bytes(pid):
 try:
  for line in (process_directory(pid)/'status').read_text().splitlines():
   if line.startswith('VmRSS:'):return int(line.split()[1])*1024
 except OSError:pass
 return None
