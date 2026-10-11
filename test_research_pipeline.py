import contextlib,gzip,io,json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from research_pipeline import run
from research_runtime import atomic_json,exclusive_lock,sha256
ROOT=Path(__file__).resolve().parent

class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.tmp.name)
 def tearDown(self):os.chdir(self.old);self.tmp.cleanup()
 def stage(self,script,**kw):
  Path('job.py').write_text(script)
  return dict(id='job',command=['{python}','job.py'],inputs=['job.py'],outputs=['out.json'],**kw)
 def execute(self,stage):
  with contextlib.redirect_stdout(io.StringIO()):return run({'stages':[stage]},'state',heartbeat=.05,poll=.02)
 def state(self):return json.loads(Path('state/state.json').read_text())
 def test_verified_skip_and_tampered_output(self):
  stage=self.stage("from pathlib import Path\nimport json\np=Path('count');n=int(p.read_text())+1 if p.exists() else 1;p.write_text(str(n));Path('out.json').write_text(json.dumps({'n':n}))")
  self.assertEqual(self.execute(stage),0);self.assertEqual(self.execute(stage),0);self.assertEqual(Path('count').read_text(),'1')
  Path('out.json').write_text('{}');self.assertEqual(self.execute(stage),0);self.assertEqual(Path('count').read_text(),'2')
 def test_failure_is_not_complete_and_retry_resume(self):
  stage=self.stage("from pathlib import Path\nimport sys\nPath('partial.pending').write_text('partial');sys.exit(1)")
  self.assertEqual(self.execute(stage),1);self.assertEqual(self.state()['status'],'failed')
  Path('job.py').write_text("from pathlib import Path\nPath('out.json').write_text('{}')")
  self.assertEqual(self.execute(stage),0)
 def test_timeout_records_signal(self):
  stage=self.stage('import time\ntime.sleep(5)',timeout_seconds=.08)
  self.assertEqual(self.execute(stage),1);s=self.state()['stages']['job'];self.assertEqual(s['failure_reason'],'timeout');self.assertEqual(s['exit_signal'],signal.SIGTERM)
 def test_missing_input_requires_restore(self):
  stage=self.stage('');Path('job.py').unlink();self.assertEqual(self.execute(stage),78);self.assertEqual(self.state()['status'],'needs_restore')
 def test_truncated_gzip_not_completed(self):
  stage=self.stage("from pathlib import Path\nPath('bad.gz').write_bytes(b'\\x1f\\x8b')");stage['outputs']=['bad.gz']
  self.assertEqual(self.execute(stage),1);self.assertEqual(self.state()['status'],'failed')
 def test_checkpoint_gate_and_stale_receipt(self):
  Path('archive.zip').write_bytes(b'fixture');stage=dict(id='saved',checkpoint=dict(archive='archive.zip',receipt='receipt.json'))
  self.assertEqual(self.execute(stage),78)
  atomic_json('receipt.json',dict(library_file_id='fixture-id',roundtrip_verified=True,sha256=sha256('archive.zip')))
  self.assertEqual(self.execute(stage),0);Path('archive.zip').write_bytes(b'changed');self.assertEqual(self.execute(stage),78)
 def test_lock_blocks_second_writer_and_releases(self):
  with exclusive_lock('lock'):
   with self.assertRaises(RuntimeError):
    with exclusive_lock('lock'):pass
  with exclusive_lock('lock'):pass
 def test_sigterm_records_interruption_and_resumes(self):
  stage=self.stage("from pathlib import Path\nimport time\nPath('ready').write_text('yes');time.sleep(10);Path('out.json').write_text('{}')")
  Path('plan.json').write_text(json.dumps({'stages':[stage]}))
  with open('runner.log','w') as log:
   child=subprocess.Popen([sys.executable,str(ROOT/'research_pipeline.py'),'--plan','plan.json','--state-dir','state','--heartbeat-seconds','.05'],stdout=log,stderr=log)
   try:
    deadline=time.monotonic()+5
    while not Path('ready').exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
    self.assertTrue(Path('ready').exists());child.send_signal(signal.SIGTERM);self.assertEqual(child.wait(timeout=6),130)
   finally:
    if child.poll() is None:child.kill();child.wait()
  self.assertEqual(self.state()['status'],'interrupted')
  Path('job.py').write_text("from pathlib import Path\nPath('out.json').write_text('{}')");self.assertEqual(self.execute(stage),0)
 def test_hard_kill_prevents_duplicate_orphan_and_recovers(self):
  stage=self.stage("from pathlib import Path\nimport time\nPath('ready').write_text('yes');time.sleep(10);Path('out.json').write_text('{}')")
  Path('plan.json').write_text(json.dumps({'stages':[stage]}))
  with open('runner.log','w') as log:
   parent=subprocess.Popen([sys.executable,str(ROOT/'research_pipeline.py'),'--plan','plan.json','--state-dir','state'],stdout=log,stderr=log)
   pid=None
   try:
    deadline=time.monotonic()+5
    while not Path('ready').exists() and parent.poll() is None and time.monotonic()<deadline:time.sleep(.02)
    self.assertTrue(Path('ready').exists());pid=self.state()['active']['pid'];parent.kill();parent.wait(timeout=5)
    self.assertEqual(self.execute(stage),75);self.assertEqual(self.state()['status'],'orphan_running')
   finally:
    if parent.poll() is None:parent.kill();parent.wait()
    if pid:
     with contextlib.suppress(ProcessLookupError):os.killpg(pid,signal.SIGTERM)
  from research_runtime import process_identity
  deadline=time.monotonic()+3
  while process_identity(pid) is not None and time.monotonic()<deadline:time.sleep(.02)
  self.assertIsNone(process_identity(pid))
  Path('job.py').write_text("from pathlib import Path\nPath('out.json').write_text('{}')");self.assertEqual(self.execute(stage),0)
 def test_resume_keeps_successful_previous_stage(self):
  Path('first.py').write_text("from pathlib import Path\np=Path('count');p.write_text(str(int(p.read_text())+1 if p.exists() else 1));Path('first.json').write_text('{}')")
  second=self.stage('import sys\nsys.exit(1)')
  first=dict(id='first',command=['{python}','first.py'],inputs=['first.py'],outputs=['first.json'])
  plan={'stages':[first,second]}
  with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(run(plan,'state',poll=.02),1)
  Path('job.py').write_text("from pathlib import Path\nPath('out.json').write_text('{}')")
  with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(run(plan,'state',poll=.02),0)
  self.assertEqual(Path('count').read_text(),'1')
if __name__=='__main__':unittest.main()
