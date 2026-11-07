"""Run the headless first-login helper with explicit private service fixtures."""
import os
from pathlib import Path
import signal,subprocess,tempfile,time,unittest
ROOT=Path(__file__).resolve().parents[1]
HELPER=ROOT/'patches/headless/overlay/usr/local/sbin/turnkey-init-first-login'
PROFILE=ROOT/'patches/headless/overlay/root/.profile.d/turnkey-init-fence'
class FirstLoginTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'bin').mkdir()
  self.defaults=self.root/'defaults';self.log=self.root/'inithooks.log';self.calls=self.root/'calls'
  self.defaults.write_text('RUN_FIRSTBOOT=false\nINITHOOKS_LOGFILE='+str(self.log)+'\n')
  self.log.write_text('INFO: Running firstboot scripts\nINFO: [40app] successfully completed\nINFO: [98finalize] successfully completed\n')
  self.helper=self.root/'first-login';self.helper.write_text(HELPER.read_text().replace('source /etc/default/inithooks','source '+str(self.defaults)).replace('/usr/sbin/turnkey-init',str(self.root/'bin/turnkey-init')))
  self.commands={'systemctl':'cat "$UNIT_STATE"','turnkey-init':'printf "interactive %s\\n" "$*" >> "$CALLS"','sleep':'printf "sleep\\n" >> "$CALLS"; cp "$NEXT_STATE" "$UNIT_STATE"'}
  self.env=dict(os.environ,PATH=str(self.root/'bin')+':'+os.environ['PATH'],UNIT_STATE=str(self.root/'unit'),NEXT_STATE=str(self.root/'next'),CALLS=str(self.calls))
  for name,body in self.commands.items():self.command(name,body)
  self.state()
 def command(self,name,body):
  p=self.root/'bin'/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
 def state(self,active='inactive',result='success',condition='yes',started='123',job='0',next=False,substate='dead'):
  (self.root/('next' if next else 'unit')).write_text(f'ActiveState={active}\nSubState={substate}\nResult={result}\nConditionResult={condition}\nExecMainStartTimestampMonotonic={started}\nJob={job}\n')
 def run_helper(self):return subprocess.run(['bash',str(self.helper)],env=self.env,capture_output=True,text=True,timeout=3)
 def test_active_boot_waits_then_enters_interactive(self):
  self.state('activating');self.state(next=True);r=self.run_helper();self.assertEqual(r.returncode,0,r.stderr);self.assertIn('Waiting for automatic setup',r.stdout);self.assertEqual(self.calls.read_text(),'sleep\ninteractive --full-confconsole\n')
 def test_container_completed_oneshot_enters_without_wait(self):
  unit=(ROOT/'patches/container/overlay/etc/systemd/system/inithooks.service').read_text();self.assertIn('Type=oneshot',unit);self.assertIn('RemainAfterExit=yes',unit)
  self.state('active',substate='exited');r=self.run_helper();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.calls.read_text(),'interactive --full-confconsole\n')
 def test_container_activating_waits_until_completed_oneshot(self):
  self.state('activating',substate='start');self.state('active',substate='exited',next=True);r=self.run_helper();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.calls.read_text(),'sleep\ninteractive --full-confconsole\n')
 def test_container_completed_unit_preserves_failed_hook(self):
  self.state('active',substate='exited');self.defaults.write_text('RUN_FIRSTBOOT=true\nINITHOOKS_LOGFILE='+str(self.log)+'\n');self.log.write_text('INFO: Running firstboot scripts\nERR: [40app] failed - exit code1\n');before=(self.defaults.read_bytes(),self.log.read_bytes());r=self.run_helper();self.assertEqual(r.returncode,1);self.assertIn('has not been retried',r.stderr);self.assertFalse(self.calls.exists());self.assertEqual(before,(self.defaults.read_bytes(),self.log.read_bytes()))
 def test_active_running_unit_still_waits(self):
  self.state('active',substate='running');self.state(next=True);r=self.run_helper();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.calls.read_text(),'sleep\ninteractive --full-confconsole\n')
 def test_completed_container_with_queued_job_still_waits(self):
  self.state('active',substate='exited',job='42');self.state('active',substate='exited',next=True);r=self.run_helper();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.calls.read_text(),'sleep\ninteractive --full-confconsole\n')
 def test_queued_unit_waits_before_execution(self):
  self.state(started='0',job='42');self.state(next=True);self.assertEqual(self.run_helper().returncode,0);self.assertTrue(self.calls.read_text().startswith('sleep\n'))
 def test_skipped_pve_unit_enters_without_wait_or_reading_setup(self):
  self.state(condition='no',started='0');self.defaults.unlink();self.log.unlink();r=self.run_helper();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.calls.read_text(),'interactive --full-confconsole\n')
 def test_completed_unit_enters_without_wait(self):
  r=self.run_helper();self.assertEqual(r.returncode,0);self.assertEqual(self.calls.read_text(),'interactive --full-confconsole\n')
 def test_failed_required_hook_not_retried_despite_unit_success(self):
  self.defaults.write_text('RUN_FIRSTBOOT=true\nINITHOOKS_LOGFILE='+str(self.log)+'\n');self.log.write_text('INFO: Running firstboot scripts\nERR: [40app] failed - exit code1\n');before=(self.defaults.read_bytes(),self.log.read_bytes());r=self.run_helper();self.assertEqual(r.returncode,1);self.assertIn('has not been retried',r.stderr);self.assertFalse(self.calls.exists());self.assertEqual(before,(self.defaults.read_bytes(),self.log.read_bytes()))
 def test_error_log_blocks_even_if_flag_was_cleared(self):
  self.log.write_text('INFO: Running firstboot scripts\nERR: [40app] failed - exit code1\nINFO: [98finalize] successfully completed\n');self.assertEqual(self.run_helper().returncode,1);self.assertFalse(self.calls.exists())
 def test_failed_unit_not_retried(self):
  self.state('failed','exit-code');self.assertEqual(self.run_helper().returncode,1);self.assertFalse(self.calls.exists())
 def test_old_error_before_latest_success_does_not_block(self):
  self.log.write_text('INFO: Running firstboot scripts\nERR: [40app] failed\n'+self.log.read_text());self.assertEqual(self.run_helper().returncode,0)
 def test_unreadable_unit_is_not_silent_retry(self):
  self.command('systemctl','exit 1');r=self.run_helper();self.assertEqual(r.returncode,1);self.assertIn('Cannot inspect',r.stderr);self.assertFalse(self.calls.exists())
 def test_cancel_wait_keeps_setup_unchanged(self):
  self.state('activating');self.command('sleep','/bin/sleep .1');before=(self.defaults.read_bytes(),self.log.read_bytes());p=subprocess.Popen(['bash',str(self.helper)],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);time.sleep(.05);p.send_signal(signal.SIGINT);out,err=p.communicate(timeout=2);self.assertEqual(p.returncode,130);self.assertIn('canceled',out);self.assertFalse(self.calls.exists());self.assertEqual(before,(self.defaults.read_bytes(),self.log.read_bytes()))
 def test_copied_admin_profile_keeps_one_command_and_socket_rewrite(self):
  original=PROFILE.read_text();self.assertEqual(len(original.splitlines()),1);admin='sudo '+original.replace('/root','/home/admin');self.assertIn('sudo /usr/bin/dtach -A /home/admin/.inithooks.dtach -Ez /usr/local/sbin/turnkey-init-first-login',admin)
if __name__=='__main__':unittest.main()
