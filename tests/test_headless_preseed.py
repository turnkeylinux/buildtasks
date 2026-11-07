"""Execute the actual headless Bash hook with private installation paths."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
HOOK=ROOT/'patches/headless/overlay/usr/lib/inithooks/firstboot.d/29preseed'
class PreseedTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.conf=self.root/'inithooks.conf';self.marker=Path(str(self.conf)+'.headless-generated.sha256')
  defaults=self.root/'defaults';defaults.write_text('INITHOOKS_CONF='+str(self.conf)+'\n')
  fence=self.root/'30turnkey-init-fence';fence.write_text('# fixture fence\n')
  source=HOOK.read_text().replace('source /etc/default/inithooks','source '+str(defaults)).replace('/usr/lib/inithooks/firstboot.d/??turnkey-init-fence*',str(fence))
  self.hook=self.root/'29preseed';self.hook.write_text(source)
  self.env={k:v for k,v in os.environ.items() if k not in ('_TURNKEY_INIT','AUTO_RUN','APP_PASS','ROOT_PASS','DB_PASS')}
 def run_hook(self,interactive=False):
  return subprocess.run(['bash','-e',str(self.hook)],env=dict(self.env,**({'_TURNKEY_INIT':'1'} if interactive else {})),capture_output=True,text=True,check=True)
 def credential_hook(self):
  # Same contract as credential hooks: load existing preseeds; prompt otherwise.
  script='''if [[ -f "$1" ]]; then source "$1"; fi
if [[ -z "$APP_PASS" ]]; then echo PROMPT_APP_PASS; read -r APP_PASS; fi
printf 'APP_PASS=%s\nAUTO_RUN=%s\n' "$APP_PASS" "${AUTO_RUN:-}"
'''
  return subprocess.run(['bash','-e','-c',script,'credential-hook',str(self.conf)],env=self.env,input='chosen-interactive-value\n',capture_output=True,text=True,check=True).stdout
 def test_failed_auto_hook_then_interactive_prompts(self):
  self.run_hook();generated=self.conf.read_bytes();self.assertIn(b'export AUTO_RUN=TRUE',generated)
  # A required-hook failure preserves configuration, as the shipped runner does.
  failed=subprocess.run(['bash','-c','source "$1"; exit 1','required-hook',str(self.conf)],env=self.env)
  self.assertEqual(failed.returncode,1);self.assertEqual(self.conf.read_bytes(),generated)
  self.run_hook(interactive=True)
  self.assertFalse(self.conf.exists());self.assertFalse(self.marker.exists())
  self.assertEqual(self.credential_hook(),'PROMPT_APP_PASS\nAPP_PASS=chosen-interactive-value\nAUTO_RUN=\n')
 def test_generated_credentials_and_marker_are_private(self):
  self.run_hook();self.assertEqual(self.conf.stat().st_mode&0o777,0o600);self.assertEqual(self.marker.stat().st_mode&0o777,0o600)
 def test_supplied_hub_or_user_preseeds_preserved(self):
  for payload in ['export APP_PASS=hub-supplied\nexport AUTO_RUN=TRUE\n','export APP_PASS=operator-supplied\n']:
   with self.subTest(payload=payload):
    self.conf.write_text(payload);self.conf.chmod(0o640);self.run_hook();self.run_hook(interactive=True)
    self.assertEqual(self.conf.read_text(),payload);self.assertEqual(self.conf.stat().st_mode&0o777,0o640);self.assertFalse(self.marker.exists());self.assertNotIn('PROMPT',self.credential_hook())
 def test_operator_edited_fallback_preserved_and_marker_consumed(self):
  self.run_hook();self.conf.write_text(self.conf.read_text()+'export APP_PASS=operator-edit\n');payload=self.conf.read_bytes()
  self.run_hook(interactive=True);self.assertEqual(self.conf.read_bytes(),payload);self.assertFalse(self.marker.exists());self.assertIn('APP_PASS=operator-edit',self.credential_hook())
 def test_successful_finalization_blank_config_not_discarded(self):
  self.run_hook();self.conf.write_text('\n') # Exact successful98finalize outcome.
  self.run_hook(interactive=True);self.assertEqual(self.conf.read_text(),'\n');self.assertFalse(self.marker.exists());self.assertIn('PROMPT_APP_PASS',self.credential_hook())
 def test_repeated_interactive_retry_idempotent(self):
  self.run_hook();self.run_hook(interactive=True);self.run_hook(interactive=True)
  self.assertFalse(self.conf.exists());self.assertFalse(self.marker.exists());self.assertIn('PROMPT_APP_PASS',self.credential_hook())
 def test_missing_config_consumes_stale_marker(self):
  self.run_hook();self.conf.unlink();self.run_hook(interactive=True);self.assertFalse(self.marker.exists())
 def test_invalid_marker_never_discards_existing_config(self):
  self.conf.write_text('export APP_PASS=preserved\n');self.marker.write_text('malformed\n');self.run_hook(interactive=True)
  self.assertEqual(self.conf.read_text(),'export APP_PASS=preserved\n');self.assertFalse(self.marker.exists())
if __name__=='__main__':unittest.main()
