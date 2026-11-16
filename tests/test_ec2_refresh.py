import importlib.machinery
import importlib.util
import os
import copy
import hashlib
import io
import json
import tarfile
from types import SimpleNamespace
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('ec2_refresh', str(ROOT / 'bt-ec2-refresh'))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)

patch_loader = importlib.machinery.SourceFileLoader('shared_patch', str(ROOT / 'patches/library-19.0-hotfix/conf/post-overlay'))
patch_spec = importlib.util.spec_from_loader(patch_loader.name, patch_loader)
shared_patch = importlib.util.module_from_spec(patch_spec)
patch_loader.exec_module(shared_patch)


class HeadlessPreseedTest(unittest.TestCase):
    def run_preseed(self, ec2=False, existing=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'inithooks.conf'
            defaults = root / 'defaults'
            defaults.write_text('INITHOOKS_CONF=' + str(config) + '\n')
            if existing is not None:
                config.write_text(existing)
            script = (ROOT / 'patches/headless/overlay/usr/lib/inithooks/firstboot.d/29preseed').read_text()
            script = script.replace('/etc/default/inithooks', str(defaults))
            script = script.replace('chmod +x /usr/lib/inithooks/firstboot.d/??turnkey-init-fence*', ':')
            if ec2:
                # The EC2 overlay applies this exact transformation after headless.
                self.assertIn("s/^export SEC_UPDATES=SKIP$/export SEC_UPDATES=FORCE/", (ROOT / 'patches/ec2/conf').read_text())
                script = script.replace('export SEC_UPDATES=SKIP', 'export SEC_UPDATES=FORCE')
            subprocess.run(['bash', '-c', script], env={'PATH': os.environ['PATH']}, check=True, capture_output=True)
            return config.read_text()

    def test_ec2_initializes_without_inherited_config_path(self):
        result = self.run_preseed(ec2=True)
        self.assertIn('export SEC_UPDATES=FORCE\n', result)
        self.assertIn('export AUTO_RUN=TRUE\n', result)

    def test_explicit_user_preseed_is_preserved(self):
        config = 'export SEC_UPDATES=SKIP\nexport APP_DOMAIN=example.org\n'
        self.assertEqual(self.run_preseed(ec2=True, existing=config), config)

    def test_other_headless_formats_keep_their_existing_choice(self):
        self.assertIn('export SEC_UPDATES=SKIP\n', self.run_preseed())


class PublicationTest(unittest.TestCase):
    def reconcile_candidate(self, visibility, customer=False):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.catalog = Mock()
        refresh.batch = 'test-batch'
        refresh.hotfix = {'release':'19.0.3'}
        refresh.args = SimpleNamespace(customer_acceptance=None)
        refresh.catalog.describe_change_set.return_value = {'Status': 'SUCCEEDED'}
        refresh.catalog.start_change_set.return_value = {'ChangeSetId': 'retirement'}
        refresh.catalog.describe_entity.return_value = {
            'EntityIdentifier': 'product@2', 'DetailsDocument': {'Description': {'Visibility': 'Public'}, 'Versions': [
                {'VersionTitle': '18.1', 'DeliveryOptions': [{'Id': 'legacy', 'Visibility': 'Public'}]},
                {'VersionTitle': '19.0', 'DeliveryOptions': [{'Id': 'old', 'Visibility': 'Public'}]},
                {'VersionTitle': '19.0.20261104', 'DeliveryOptions': [{'Id': 'new', 'Visibility': visibility}]},
            ]}}
        item = {'app': 'core', 'product_id': 'product', 'version': '19.0.20261104', 'change_set_id': 'addition', 'superseded_delivery_ids': ['old']}
        with tempfile.TemporaryDirectory() as directory:
            refresh.state = Path(directory)
            with patch.object(module, 'qa_receipt', return_value='proof' if customer else None):
                refresh.reconcile(item)
        return refresh, item

    def test_old_delivery_stays_public_until_replacement_is_public(self):
        refresh, item = self.reconcile_candidate('Restricted')
        refresh.catalog.start_change_set.assert_not_called()
        self.assertFalse(item['new_delivery_public'])

    def test_only_superseded_delivery_is_retired(self):
        refresh, item = self.reconcile_candidate('Public', customer=True)
        request = refresh.catalog.start_change_set.call_args.kwargs['ChangeSet'][0]
        self.assertEqual(request['ChangeType'], 'RestrictDeliveryOptions')
        self.assertEqual(request['DetailsDocument']['DeliveryOptionIds'], ['old'])
        self.assertEqual(item['retirement_status'], 'SUCCEEDED')

    def test_public_approval_without_customer_qa_never_retires(self):
        refresh, item = self.reconcile_candidate('Public')
        self.assertTrue(item['new_delivery_public'])
        self.assertFalse(item['customer_verified'])
        refresh.catalog.start_change_set.assert_not_called()

    def test_unverified_image_cannot_be_submitted(self):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.catalog = Mock()
        with self.assertRaisesRegex(ValueError, 'verified boot'):
            refresh.publish({'ami': 'ami-candidate'})
        refresh.catalog.start_change_set.assert_not_called()

    def test_new_instance_visibility_is_retryable(self):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.ec2 = Mock()
        refresh.ec2.describe_instances.side_effect = ClientError(
            {'Error': {'Code': 'InvalidInstanceID.NotFound', 'Message': 'not yet propagated'}}, 'DescribeInstances')
        self.assertEqual(refresh.instance('i-new')['State']['Name'], 'pending')

    def test_other_aws_errors_are_not_hidden(self):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.ec2 = Mock()
        refresh.ec2.describe_instances.side_effect = ClientError(
            {'Error': {'Code': 'UnauthorizedOperation', 'Message': 'denied'}}, 'DescribeInstances')
        with self.assertRaises(ClientError):
            refresh.instance('i-new')


class BootReadinessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys=tempfile.TemporaryDirectory();cls.records=[]
        for name in ('stock','final'):
            key=Path(cls.keys.name)/name
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
            cls.records.append(' '.join(key.with_suffix('.pub').read_text().split()[:2]))

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.calls=[];self.snapshots=[]
        self.refresh=module.Refresh.__new__(module.Refresh)
        self.refresh.state=self.base;self.refresh.key=self.base/'worker-key'
        self.refresh.host_key_lock=module.threading.Lock();self.refresh.batch='fixture'
        self.refresh.resources={};self.refresh.hotfix=None;self.refresh.log=Mock()
        self.refresh.ec2=Mock()
        self.refresh.instance=Mock(return_value={'State':{'Name':'running'},'PublicIpAddress':'127.0.0.1'})
        self.item={'app':'core','ami':'ami-test','test_instance':'i-test'}
        self.real_run=subprocess.run

    def run_boot(self, events, max_polls=None):
        events=list(events);poll_limit=max_polls or len(events);events=iter(events);self.polls=0
        def transport(args, **kwargs):
            if args[0]=='ssh-keygen':
                self.calls.append(('lookup',args))
                return self.real_run(args,**kwargs)
            self.assertEqual(args[0],'ssh')
            known=Path(next(arg.split('=',1)[1] for arg in args if arg.startswith('UserKnownHostsFile=')))
            command=args[-1];self.calls.append(('ssh',known,command))
            if command=='sudo bash -s':
                self.assertIn(self.records[1],known.read_text())
                return SimpleNamespace(returncode=0,stdout='BOOT_VERIFIED brotli=fixture\n',stderr='')
            event=next(events)
            kind,key=event
            current=self.real_run(['ssh-keygen','-F','i-test','-f',str(known)],capture_output=True,text=True)
            entries=[line for line in current.stdout.splitlines() if line and not line.startswith('#')]
            if entries and not any(key in line for line in entries):
                return SimpleNamespace(returncode=255,stdout='',stderr='Host key verification failed')
            if not entries:
                with known.open('a') as stream:stream.write('i-test '+key+'\n')
            if kind=='timeout':raise subprocess.TimeoutExpired(args,12)
            if kind=='denied':return SimpleNamespace(returncode=255,stdout='ActiveState=failed\n',stderr='Permission denied')
            if kind=='command-error':return SimpleNamespace(returncode=1,stdout='',stderr='not ready')
            if kind=='failed':return SimpleNamespace(returncode=0,stdout='Result=exit-code\nActiveState=failed\nERR: fixture detail\n',stderr='fixture stderr\n')
            if kind=='waiting':return SimpleNamespace(returncode=0,stdout='Result=success\nActiveState=activating\n',stderr='')
            return SimpleNamespace(returncode=0,stdout='Result=success\nActiveState=inactive\nInithooks run completed\n',stderr='')
        def wait(check,seconds,delay=5):
            if seconds==180:return check()
            for _ in range(poll_limit):
                self.polls+=1
                if check():return True
                pins=self.base/'known_hosts'
                self.snapshots.append(pins.read_bytes() if pins.exists() else b'')
                self.assertFalse(list(self.base.glob('boot-host-*')))
            pins=self.base/'known_hosts'
            stale=pins.exists() and ('i-test '+self.records[0]) in pins.read_text()
            raise TimeoutError('fixture readiness polls exhausted; stale_instance_stock_pin='+str(stale))
        with patch.object(module.subprocess,'run',side_effect=transport),patch.object(module,'wait_until',side_effect=wait):
            self.refresh.boot_test(self.item)

    def test_failed_authentication_never_pins_stock_key_before_rotation(self):
        known=self.base/'known_hosts';worker='worker-host '+self.records[0]+'\n';known.write_text(worker)
        self.run_boot([('denied',self.records[0]),('ready',self.records[1])])
        self.assertEqual(self.snapshots,[worker.encode()])
        self.assertEqual(known.read_text(),worker+'i-test '+self.records[1]+'\n')
        self.assertFalse(list(self.base.glob('boot-host-*')))
        self.assertEqual(len([c for c in self.calls if c[0]=='lookup']),2)
        self.refresh.ec2.terminate_instances.assert_called_once_with(InstanceIds=['i-test'])

    def test_timeout_and_failed_remote_command_discard_attempt_pins(self):
        self.run_boot([('timeout',self.records[0]),('command-error',self.records[1]),('ready',self.records[1])])
        self.assertEqual(self.snapshots,[b'',b''])
        self.assertEqual((self.base/'known_hosts').read_text(),'i-test '+self.records[1]+'\n')
        self.assertFalse(list(self.base.glob('boot-host-*')))

    def test_first_authenticated_waiting_probe_pins_once_then_uses_durable_key(self):
        self.run_boot([('waiting',self.records[1]),('ready',self.records[1])])
        ssh=[c for c in self.calls if c[0]=='ssh']
        self.assertNotEqual(ssh[0][1],self.base/'known_hosts')
        self.assertEqual([c[1] for c in ssh[1:]],[self.base/'known_hosts']*2)
        self.assertEqual(self.snapshots,[('i-test '+self.records[1]+'\n').encode()])

    def test_existing_pin_is_never_replaced_after_key_mismatch(self):
        known=self.base/'known_hosts';original='i-test '+self.records[0]+'\n';known.write_text(original)
        with self.assertRaises(TimeoutError):
            self.run_boot([('ready',self.records[1])]*2,max_polls=2)
        self.assertEqual(known.read_text(),original)
        self.assertEqual(len([c for c in self.calls if c[0]=='lookup']),1)
        self.assertTrue(all(c[1]==known for c in self.calls if c[0]=='ssh'))

    def test_already_pinned_success_keeps_one_readiness_network_call(self):
        known=self.base/'known_hosts';known.write_text('i-test '+self.records[1]+'\n')
        self.run_boot([('ready',self.records[1])])
        ssh=[c for c in self.calls if c[0]=='ssh']
        self.assertEqual(len(ssh),2)  # One readiness probe and the unchanged final verification.
        self.assertEqual(self.polls,1)
        self.assertTrue(all(c[1]==known for c in ssh))
        self.assertEqual(len([c for c in self.calls if c[0]=='lookup']),1)

    def test_authenticated_initialization_failure_is_private_and_immediate(self):
        with self.assertRaisesRegex(RuntimeError,'First-boot initialization failed'):
            self.run_boot([('failed',self.records[1])])
        self.assertEqual(self.polls,1)
        failure=self.base/'core-boot-readiness-failure.log'
        self.assertIn('Result=exit-code',failure.read_text())
        self.assertIn('fixture stderr',failure.read_text())
        self.assertEqual(failure.stat().st_mode&0o777,0o600)
        self.assertFalse(list(self.base.glob('boot-host-*')))
        self.refresh.ec2.terminate_instances.assert_called_once_with(InstanceIds=['i-test'])

    def test_normal_ssh_has_no_new_probe_or_global_hostkey_override(self):
        with patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            self.refresh.ssh('127.0.0.1','true',host_alias='worker-host')
        run.assert_called_once()
        argv=run.call_args.args[0]
        self.assertEqual(argv[0],'ssh')
        self.assertIn('UserKnownHostsFile='+str(self.base/'known_hosts'),argv)
        self.assertNotIn('GlobalKnownHostsFile=/dev/null',argv)

    def test_concurrent_fresh_guests_append_both_keys_and_preserve_worker_pin(self):
        known=self.base/'known_hosts';worker='worker-host '+self.records[0]
        known.write_text(worker+'\n');barrier=module.threading.Barrier(2)
        keys={'i-one':self.records[0],'i-two':self.records[1]}
        def transport(args,**kwargs):
            if args[0]=='ssh-keygen':return self.real_run(args,**kwargs)
            iid=next(arg.split('=',1)[1] for arg in args if arg.startswith('HostKeyAlias='))
            record=iid+' '+keys[iid]+'\n'
            target=Path(next(arg.split('=',1)[1] for arg in args if arg.startswith('UserKnownHostsFile=')))
            if args[-1]=='sudo bash -s':
                self.assertIn(record,target.read_text())
                return SimpleNamespace(returncode=0,stdout='BOOT_VERIFIED\n',stderr='')
            self.assertNotEqual(target,known)
            target.write_text(record);barrier.wait(timeout=5)
            return SimpleNamespace(returncode=0,stdout='ActiveState=inactive\nInithooks run completed\n',stderr='')
        def wait(check,seconds,delay=5):
            result=check();self.assertTrue(result);return result
        with patch.object(module.subprocess,'run',side_effect=transport),patch.object(module,'wait_until',side_effect=wait):
            with module.futures.ThreadPoolExecutor(max_workers=2) as pool:
                jobs=[pool.submit(self.refresh.boot_test,dict(app='core-'+iid,ami='ami-test',test_instance=iid)) for iid in keys]
                for job in jobs:job.result(timeout=10)
        self.assertEqual(set(known.read_text().splitlines()),{worker}|{iid+' '+key for iid,key in keys.items()})
        self.assertFalse(list(self.base.glob('boot-host-*')))


class ClientTokenTest(unittest.TestCase):
    def test_existing_tokens_keep_their_idempotency_identity(self):
        for token in ['batch-core-r1', 'x' * 64]:
            self.assertEqual(module.ec2_client_token(token), token)

    def test_long_tokens_are_stable_and_distinguish_attempts(self):
        token = 'x' * 60 + '-test-lighttpd-php-fastcgi-r1-1'
        first = module.ec2_client_token(token)
        self.assertEqual(len(first), 64)
        self.assertEqual(first, module.ec2_client_token(token))
        self.assertNotEqual(first, module.ec2_client_token(token[:-1] + '2'))

    def test_long_appliance_name_sends_an_accepted_boot_request_token(self):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.batch = 'tkl-use1-refresh-benchmark-20261104'
        refresh.resources = dict(key_name='test-key', subnet='subnet-test', security_group='sg-test')
        refresh.ec2 = Mock()
        refresh.ec2.run_instances.side_effect = RuntimeError('request captured')
        with tempfile.TemporaryDirectory() as directory:
            refresh.state = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'request captured'):
                refresh.boot_test(dict(app='lighttpd-php-fastcgi', ami='ami-test'))
        self.assertLessEqual(len(refresh.ec2.run_instances.call_args.kwargs['ClientToken']), 64)


class HotfixInputTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.commit = 'a' * 40
        def asset(name, body=b'fixture'):
            path = self.base / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            return {'path': name, 'sha256': module.hotfix.sha(path), 'source_main': self.commit}
        self.data = {'release': '19.0.3', 'technical_release': '19.0.3.12', 'release_notes': 'Current maintenance fixes.',
                     'sources': {name: self.commit for name in ['buildtasks_main', 'common_main', 'release_main', 'controller_main']},
                     'packages': {name: {**{key: shared_patch.PINS[name][key] for key in ('version', 'sha256')}, 'source_main': self.commit} for name in module.hotfix.PACKAGES},
                     'minimum_packages': {'hubdns': '1.5.0', 'hubclient': '0.3.0', 'webmin': '2.660.turnkey0', 'sudo': '1.9.16p2-3+deb13u2'},
                     'profile_generator': asset('generator'), 'aptconf_tag': asset('apt-tag'),
                     'apps': {'lamp': {'source_ami': 'ami-123', 'source_snapshot': 'snap-123', 'source_main': self.commit,
                                      'identity_package': asset('identity.deb'), 'superseded_delivery_ids': ['old'],
                                      'profile_conf': {'core': asset('conf/core'), 'lamp': asset('conf/lamp'),
                                                       'hooks/lamp/50-export': {**asset('conf/hook'), 'mode': 0o755}}}}}
        bundle = self.base / 'library-19.0-hotfix.tar.gz'
        with tarfile.open(bundle, 'w:gz') as archive:
            archive.add(ROOT / 'patches/library-19.0-hotfix', arcname='library-19.0-hotfix')
        self.data['shared_patch'] = {'path': bundle.name, 'sha256': module.hotfix.sha(bundle), 'source_main': self.commit}
        self.manifest = self.base / 'input.json'; self.write()

    def write(self):
        self.manifest.write_text(json.dumps(self.data))

    def test_manifest_freezes_hashes_and_preserves_hooks(self):
        frozen = module.hotfix.freeze(self.manifest, self.base / 'retained')
        self.assertEqual(module.hotfix.load(frozen), self.data)
        (self.base / 'conf/hook').write_bytes(b'changed after freeze')
        self.assertEqual(module.hotfix.load(frozen), self.data)
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            module.hotfix.load(self.manifest)

    def test_missing_package_or_source_binding_is_rejected(self):
        for field in ['profile_conf', 'source_snapshot']:
            original = copy.deepcopy(self.data)
            del self.data['apps']['lamp'][field]; self.write()
            with self.assertRaises((ValueError, KeyError)):
                module.hotfix.load(self.manifest)
            self.data = original
        del self.data['packages']['tklbam']; self.write()
        with self.assertRaisesRegex(ValueError, 'incomplete package'):
            module.hotfix.load(self.manifest)

    def test_other_format_profile_identity_is_rejected(self):
        self.data['technical_release'] = '19.0.3.2'; self.write()
        with self.assertRaisesRegex(ValueError, 'EC2 hotfix identity'):
            module.hotfix.load(self.manifest)

    def test_ec2_technical_ids_allow_fresh_immutable_profiles(self):
        for technical in ('19.0.3.12','19.0.3.13'):
            with self.subTest(technical=technical):
                self.data['technical_release']=technical;self.write()
                self.assertEqual(module.hotfix.load(self.manifest)['technical_release'],technical)

    def test_ec2_technical_ids_reject_reserved_and_invalid_values(self):
        for technical in ('19.0.3.0','19.0.3.3','19.0.3.11','19.0.4.13','19.1.0.13',
                          '19.0.3.013','19.0.3.13x','19.0.3.13.1',None,13,True,[],{}):
            with self.subTest(technical=technical):
                self.data['technical_release']=technical;self.write()
                with self.assertRaisesRegex(ValueError,'EC2 hotfix identity'):
                    module.hotfix.load(self.manifest)
        self.data['technical_release']='19.0.3.13'
        self.data['release']='19.1';self.write()
        with self.assertRaisesRegex(ValueError,'EC2 hotfix identity'):
            module.hotfix.load(self.manifest)

    def factory(self):
        root = self.base / 'root'
        for name in ['etc/default', 'etc/webmin', 'run', 'var/lib/turnkey-info', 'root', 'home']:
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / 'etc/os-release').write_text('ID=debian\nVERSION_ID="13"\n')
        (root / 'etc/default/inithooks').write_text('RUN_FIRSTBOOT=true\n')
        (root / 'etc/webmin/miniserv.conf').write_text('port=12321\ncustom=value\n')
        (root / 'etc/turnkey_version').write_text('turnkey-lamp-19.0.3.12-trixie-amd64\n')
        (root / 'var/lib/turnkey-info/hotfix.json').write_text('{}')
        return root

    def test_initialized_root_is_refused(self):
        root = self.factory()
        (root / 'etc/default/inithooks').write_text('RUN_FIRSTBOOT=false\n')
        with self.assertRaisesRegex(ValueError, 'completed setup'):
            module.hotfix.factory(root)

    def test_package_install_checks_signed_candidate_before_installing(self):
        root = self.factory(); self.bad_candidate = True
        with self.assertRaisesRegex(ValueError, 'signed APT candidate hash'):
            self.install(root)
        self.assertFalse(any('apt-get' in c for c in self.calls))

    def install(self, root):
        self.calls = calls = []
        installed = dict(getattr(self, 'installed', {name: pin['version'] for name, pin in shared_patch.PINS.items()}))
        refreshed = False
        real_run = subprocess.run
        def process(args, **kwargs):
            nonlocal refreshed
            args = list(map(str, args)); calls.append(args)
            result = SimpleNamespace(returncode=0, stdout='')
            if args[:2] == ['dpkg', '--print-architecture']:
                result.stdout = getattr(self, 'architecture', 'amd64')
            elif args[0] == 'sudo':result.stdout = getattr(self, 'sudo_uid', '0')
            elif args[0] == 'visudo':pass
            elif args[0] == '/usr/sbin/policy-rc.d':result.returncode = 101
            elif args[0] == 'dpkg-query':result.stdout = installed[args[-1]]
            elif args[0] == 'apt-cache':
                name = args[-1].split('=')[0]
                if not getattr(self, 'missing_candidate', False) or refreshed:
                    result.stdout = 'SHA256: ' + ('c'*64 if getattr(self, 'bad_candidate', False) else shared_patch.PINS[name]['sha256'])
            elif args[0] == 'apt-get' and args[-1] == 'update':refreshed = True
            elif args[0] == 'apt-get' and 'install' in args:
                installed.update(target.split('=', 1) for target in args[args.index('install')+1:])
            elif args[:2] == ['dpkg', '--compare-versions']:return real_run(args, **kwargs)
            else:raise AssertionError(args)
            return result
        def command(args):
            args=list(map(str,args)); calls.append(args)
            if args[0] == 'tklpatch-apply':
                with patch.object(shared_patch, 'ROOT', root), patch.object(shared_patch.subprocess, 'run', side_effect=process):shared_patch.apply()
            if args[0] == 'tklpatch-apply-overlay':
                real_run([str(Path(os.environ['TKLPATCH_TEST_BIN'])/'tklpatch-apply-overlay'), *args[1:]], check=True, capture_output=True, text=True)
            if 'dpkg-query' in args:return 'turnkey-lamp-19.0' if args[-1]=='-f=${Package}\n' else self.data['minimum_packages'].get(args[-1], self.data['packages'].get(args[-1],{}).get('version','1'))
            if args[0]=='dpkg-deb':return 'turnkey-lamp-19.0.3.12' if args[-1]=='Package' else '1'
            return ''
        with patch.object(module.hotfix,'run',side_effect=command):
            module.hotfix.install(root,self.manifest,'lamp')
        return calls

    def test_install_preserves_settings_and_uses_only_frozen_package_targets(self):
        root=self.factory(); calls=self.install(root)
        config=(root/'etc/webmin/miniserv.conf').read_text()
        self.assertIn('custom=value\n',config)
        self.assertIn('extracas=/etc/ssl/private/cert.pem\n',config)
        self.assertEqual((root/'etc/turnkey_version').read_text(),'turnkey-lamp-19.0.3.12-trixie-amd64\n')
        apt=next(args for args in calls if 'apt-get' in args)
        self.assertEqual(set(apt[apt.index('install')+1:]),{name+'='+self.data['packages'][name]['version'] for name in module.hotfix.PACKAGES})
        self.assertIn('APT::Get::AllowUnauthenticated=false',apt)
        self.assertIn('--no-remove',apt);self.assertIn('DPkg::Options::=--force-confold',apt)
        self.assertTrue(any('--purge' in args and 'turnkey-lamp-19.0' in args for args in calls))

    def test_root_sudo_compatibility_is_required(self):
        root = self.factory()
        self.sudo_uid = '1000'
        with self.assertRaisesRegex(ValueError, 'root sudo compatibility failed'):
            self.install(root)

    def test_install_normalizes_single_stock_empty_webmin_chain(self):
        root = self.factory(); config = root / 'etc/webmin/miniserv.conf'
        config.write_text('port=12321\nextracas=\ncustom=value\n')
        self.install(root)
        self.assertEqual(config.read_text(), 'port=12321\nextracas=/etc/ssl/private/cert.pem\ncustom=value\n')

    def test_install_preserves_canonical_webmin_chain_idempotently(self):
        root = self.factory(); config = root / 'etc/webmin/miniserv.conf'
        original = 'port=12321\nextracas=/etc/ssl/private/cert.pem\ncustom=value\n'
        config.write_text(original)
        os.utime(config, ns=(1_000_000_000, 1_000_000_000))
        self.install(root)
        self.install(root)
        self.assertEqual(config.read_text(), original)
        self.assertEqual(config.stat().st_mtime_ns, 1_000_000_000)

    def test_install_rejects_custom_or_duplicate_webmin_chain(self):
        root = self.factory(); config = root / 'etc/webmin/miniserv.conf'
        for chain in [
                'extracas=/etc/custom.pem\n',
                'extracas=\nextracas=\n',
                'extracas=/etc/ssl/private/cert.pem\nextracas=/etc/ssl/private/cert.pem\n',
                'extracas=\nextracas=/etc/ssl/private/cert.pem\n']:
            with self.subTest(chain=chain):
                original = 'port=12321\n' + chain + 'custom=value\n'
                config.write_text(original)
                with self.assertRaisesRegex(ValueError, 'different Webmin chain'):
                    self.install(root)
                self.assertEqual(config.read_text(), original)

    def test_standard_patch_delegation_and_cached_metadata_avoid_update(self):
        root=self.factory(); calls=self.install(root)
        self.assertIn(['tklpatch-apply',str(root),str(self.base/'library-19.0-hotfix.tar.gz')], calls)
        self.assertFalse(any(args[-1:] == ['update'] for args in calls))

    def test_absent_candidate_refreshes_once_and_newer_floor_is_preserved(self):
        root=self.factory(); self.missing_candidate=True
        self.installed={name: pin['version'] for name,pin in shared_patch.PINS.items()}
        self.installed['hubdns']='9.0'
        calls=self.install(root)
        self.assertEqual(1, len([args for args in calls if args[-1:] == ['update']]))
        apt=next(args for args in calls if 'apt-get' in args and 'install' in args)
        self.assertFalse(any(x.startswith('hubdns=') for x in apt))

    def test_common_conf_refuses_wrong_os_arch_or_authorized_keys(self):
        root=self.factory(); before=(root/'etc/webmin/miniserv.conf').read_bytes()
        for kind in ('os', 'arch', 'keys', 'release'):
            with self.subTest(kind=kind):
                (root/'etc/os-release').write_text('ID=debian\nVERSION_ID="12"\n' if kind=='os' else 'ID=debian\nVERSION_ID="13"\n')
                self.architecture='arm64' if kind=='arch' else 'amd64'
                (root/'etc/turnkey_version').write_text('turnkey-lamp-19.1-trixie-amd64\n' if kind=='release' else 'turnkey-lamp-19.0-trixie-amd64\n')
                key=root/'root/authorized_keys'
                if kind=='keys':key.write_text('synthetic public fixture')
                with self.assertRaisesRegex(ValueError, 'Debian 13|amd64|authorized keys|TurnKey 19.0'):self.install(root)
                self.assertFalse(any('apt-get' in args for args in self.calls))
                self.assertEqual(before,(root/'etc/webmin/miniserv.conf').read_bytes())
                if key.exists():key.unlink()

    def test_manifest_cannot_substitute_shared_pins_or_tamper_archive(self):
        self.data['packages']['tklbam']['sha256']='c'*64;self.write()
        with self.assertRaisesRegex(ValueError,'shared patch package differs'):module.hotfix.load(self.manifest)
        self.data['packages']['tklbam']['sha256']=shared_patch.PINS['tklbam']['sha256'];self.write()
        (self.base/'library-19.0-hotfix.tar.gz').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'hash differs'):module.hotfix.load(self.manifest)

    def test_older_floor_uses_pinned_signed_package(self):
        root=self.factory();self.installed={name:pin['version'] for name,pin in shared_patch.PINS.items()};self.installed['hubdns']='1.4.0'
        calls=self.install(root);apt=next(args for args in calls if 'apt-get' in args and 'install' in args)
        self.assertIn('hubdns=1.5.0',apt)

    def test_shared_archive_source_guard_uses_frozen_commit_timestamp(self):
        import gzip
        canonical=gzip.decompress((self.base/'library-19.0-hotfix.tar.gz').read_bytes())
        def git(args):
            if 'archive' in args:
                self.assertIn('--mtime=@1794620000',args);return canonical
            if '--format=%ct' in args:return b'1794620000\n'
            member=args[-1].split(':',1)[1]
            if member=='bin/generate-tklbam-profile':return (self.base/'generator').read_bytes()
            if member=='bin/aptconf-tag':return (self.base/'apt-tag').read_bytes()
            return (ROOT/member).read_bytes()
        with patch.object(module.subprocess,'run'),patch.object(module.subprocess,'check_output',side_effect=git):
            module.verify_controller_source(self.data,self.manifest)
            bundle=self.base/'library-19.0-hotfix.tar.gz';bundle.write_bytes(gzip.compress(b'changed source'))
            self.data['shared_patch']['sha256']=module.hotfix.sha(bundle)
            with self.assertRaisesRegex(ValueError,'TKLPatch differs'):module.verify_controller_source(self.data,self.manifest)

    def test_packaged_tklpatch_advanced_hook_transports_pins_and_cleans_script(self):
        tool=os.environ.get('TKLPATCH_TEST_BIN')
        if not tool:self.skipTest('Set TKLPATCH_TEST_BIN to the hash-verified public0.95 fixture')
        root=self.factory();tools=self.base/'tool-shims';tools.mkdir()
        shim=tools/'tklpatch-chroot'
        shim.write_text('#!/bin/sh\nset -eu\nif [ "$2" = /tmp/tklpatch/post-overlay ]; then\n test -x "$1/tmp/tklpatch/post-overlay"\n cmp "$1/tmp/tklpatch/packages.json" "$EXPECTED_PINS"\n touch "$1/conf-transported"\nfi\n')
        shim.chmod(0o755);env=dict(os.environ,PATH=str(tools)+':'+tool+':'+os.environ['PATH'],EXPECTED_PINS=str(ROOT/'patches/library-19.0-hotfix/conf/packages.json'))
        result=subprocess.run([str(Path(tool)/'tklpatch-apply'),str(root),str(self.base/'library-19.0-hotfix.tar.gz')],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue((root/'conf-transported').exists());self.assertFalse((root/'tmp/tklpatch').exists())

    def test_genuine_overlay_enforces_requested_target_modes_and_preserves_ownership(self):
        if not os.environ.get('TKLPATCH_TEST_BIN'):self.skipTest('Requires hash-verified public0.95 fixture')
        root=self.factory();source=self.base/'mode-overlay';source.write_bytes(b'new mode-contract payload')
        for requested in (0o755,0o600):
            with self.subTest(requested=oct(requested)):
                target=root/'etc/mode-contract';target.write_bytes(b'old payload');target.chmod(0o644)
                before=target.stat();parent_before=target.parent.stat()
                self.data['apps']['lamp']['overlay']=[{'path':source.name,'sha256':module.hotfix.sha(source),
                    'source_main':self.commit,'target':'/etc/mode-contract','previous_sha256':[module.hotfix.sha(target)],'mode':requested}]
                self.write();self.install(root);after=target.stat();parent_after=target.parent.stat()
                self.assertEqual(target.read_bytes(),source.read_bytes())
                self.assertEqual((after.st_uid,after.st_gid),(before.st_uid,before.st_gid))
                self.assertEqual(parent_after.st_mode,parent_before.st_mode)
                self.assertEqual(after.st_mode&0o777,requested)

    def new_file_overlay(self, target, previous=(None,)):
        source=self.base/'new-overlay';source.write_bytes(b'[Unit]\nAfter=mariadb.service\n')
        self.data['apps']['lamp']['overlay']=[{'path':source.name,'sha256':module.hotfix.sha(source),
            'source_main':self.commit,'target':target,'previous_sha256':list(previous),'mode':0o644}]
        self.write()
        return source

    def test_genuine_overlay_creates_only_explicitly_accepted_absent_file(self):
        if not os.environ.get('TKLPATCH_TEST_BIN'):self.skipTest('Requires hash-verified public0.95 fixture')
        root=self.factory();target=root/'usr/lib/systemd/system/inithooks.service.d/20-mariadb.conf'
        source=self.new_file_overlay('/'+str(target.relative_to(root)))
        self.install(root)
        self.assertEqual(target.read_bytes(),source.read_bytes())
        self.assertEqual(target.stat().st_mode&0o777,0o644)
        self.assertEqual((target.stat().st_uid,target.stat().st_gid),(root.stat().st_uid,root.stat().st_gid))

    def test_absent_overlay_target_requires_explicit_none(self):
        root=self.factory();target=root/'etc/not-approved.conf'
        self.new_file_overlay('/etc/not-approved.conf',previous=())
        with self.assertRaisesRegex(ValueError,'overlay'):
            self.install(root)
        self.assertFalse(target.exists())

    def test_new_overlay_refuses_collisions_and_parent_escape(self):
        root=self.factory();outside=self.base/'outside';outside.mkdir()
        for kind in ('unknown-file','directory','dangling-link','parent-escape'):
            with self.subTest(kind=kind):
                target=root/'etc'/kind
                if kind=='unknown-file':target.write_bytes(b'keep existing unknown bytes')
                elif kind=='directory':target.mkdir()
                elif kind=='dangling-link':target.symlink_to('missing-target')
                else:
                    target.symlink_to(outside,target_is_directory=True)
                    target=target/'20-mariadb.conf'
                self.new_file_overlay('/'+str(target.relative_to(root)))
                with self.assertRaisesRegex(ValueError,'overlay'):
                    self.install(root)
                if kind=='unknown-file':self.assertEqual(target.read_bytes(),b'keep existing unknown bytes')
                elif kind=='directory':self.assertTrue(target.is_dir())
                elif kind=='dangling-link':self.assertTrue(target.is_symlink())
                else:self.assertFalse((outside/'20-mariadb.conf').exists())

    def worker_tool_fixture(self, present):
        tools=self.base/('worker-tools-'+str(len(present))+'-'.join(present));tools.mkdir()
        for name in present:
            target=tools/name;target.write_text('#!/bin/sh\nexit 0\n');target.chmod(0o755)
        refresh=module.Refresh.__new__(module.Refresh);refresh.hotfix=self.data;refresh.hotfix_path=self.manifest;refresh.batch='fixture'
        calls=[]
        def ssh(ip,command,**kwargs):
            calls.append(command)
            if command.startswith('command -v'):
                return subprocess.run(['/bin/bash','-c',command],env=dict(os.environ,PATH=str(tools)),capture_output=True,text=True)
            return SimpleNamespace(returncode=0,stderr='')
        refresh.ssh=ssh
        return refresh,calls

    def test_missing_either_worker_tool_blocks_asset_mutation(self):
        for present in (('tklpatch-apply',),('tklpatch-apply-overlay',)):
            with self.subTest(present=present):
                refresh,calls=self.worker_tool_fixture(present)
                with self.assertRaisesRegex(RuntimeError,'requires qualified TKLPatch'):refresh.prepare_worker({'ip':'fixture'})
                self.assertFalse(any(command.startswith(('cat >','mkdir -p')) for command in calls))

    def test_both_worker_tools_allow_normal_asset_staging(self):
        refresh,calls=self.worker_tool_fixture(('tklpatch-apply','tklpatch-apply-overlay','zerofree'))
        refresh.prepare_worker({'ip':'fixture'})
        self.assertTrue(any(command.startswith('cat >') for command in calls))
        self.assertTrue(any(command.startswith('mkdir -p') for command in calls))

    def test_profile_refuses_pending_patch_transport_or_resolver_fixture(self):
        root=self.factory();(root/'tmp/tklpatch').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'cleanup is incomplete'):
            module.hotfix.profile(root,self.manifest,'lamp',self.base/'profile')

    def test_profile_uses_final_readonly_root_and_retains_hook_mode(self):
        root = self.factory(); output = self.base / 'output'; calls = []
        def command(args):
            args = list(map(str, args)); calls.append(args)
            if '/usr/lib/tklbam-pypy2/bin/pypy' in args:
                work = next((root / 'run').glob('ec2-profile-*')) / 'work'
                self.assertEqual((work/'profile-conf/hooks/lamp/50-export').stat().st_mode & 0o777, 0o755)
                (output / 'turnkey-lamp-19.0.3.12-trixie-amd64.tar.gz').write_bytes(b'generated profile')
            if 'dpkg-query' in args:
                return 'tklbam\t1.5.5\tinstall ok installed'
            return ''
        with patch.object(module.hotfix, 'run', side_effect=command):
            receipt = module.hotfix.profile(root, self.manifest, 'lamp', output)
        self.assertTrue(receipt['pristine'])
        self.assertEqual(receipt['manifest_sha256'], module.hotfix.sha(self.manifest))
        self.assertEqual(receipt['source_ami'], 'ami-123')
        index = next(i for i,a in enumerate(calls) if '/usr/lib/tklbam-pypy2/bin/pypy' in a)
        self.assertTrue(any(a[:3] == ['mount','-o','remount,bind,ro'] for a in calls[:index]))
        self.assertEqual(len([a for a in calls if a[0] == 'umount']), 2)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            module.hotfix.profile(root, self.manifest, 'lamp', output)

    def test_profile_publication_gate_cannot_boot_before_readback(self):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.hotfix = self.data; refresh.state = self.base; refresh.args = SimpleNamespace(publish=False, profile_publications=None)
        refresh.boot_test = Mock(); refresh.log = Mock()
        item = {'app': 'lamp', 'ami': 'ami-new', 'volume_deleted': True, 'profile': {'identity':'id','profile_sha256':'x'}}
        refresh.finish(item)
        refresh.boot_test.assert_not_called()
        self.assertEqual(item['status'], 'PROFILE_PENDING_PUBLICATION')

    def test_wrong_profile_readback_is_rejected(self):
        refresh = module.Refresh.__new__(module.Refresh)
        proof = self.base / 'published.json'; proof.write_text(json.dumps({'lamp': {'identity':'id','profile_sha256':'wrong','public_readback_sha256':'wrong','url':'https://example.test/id'}}))
        refresh.args = SimpleNamespace(profile_publications=str(proof))
        with self.assertRaisesRegex(ValueError, 'profile receipt differs'):
            refresh.profile_published({'app':'lamp','profile': {'identity':'id','profile_sha256':'expected'}})

    def test_source_qa_is_required_before_hotfix_submission(self):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.hotfix = self.data; refresh.state = self.base; refresh.args = SimpleNamespace(source_acceptance=None); refresh.catalog = Mock()
        item = {'app':'lamp','ami':'ami-new','boot_verified':True}
        refresh.publish(item)
        self.assertEqual(item['status'], 'WAIT_SOURCE_QA')
        refresh.catalog.list_change_sets.assert_not_called()

    def test_apps_selection_rejects_typo_and_preserves_order(self):
        rows = [{'app':'core'},{'app':'lamp'}]
        self.assertEqual(module.selected_rows(rows,'lamp'), [{'app':'lamp'}])
        with self.assertRaisesRegex(ValueError,'Unknown apps'):
            module.selected_rows(rows,'lmap')

    def test_prepare_unknown_apps_stops_before_aws(self):
        previous = self.base / 'old'; previous.mkdir()
        (previous/'resources.json').write_text(json.dumps({'region':'us-east-1','account':'account'}))
        (previous/'plan.json').write_text(json.dumps([{'app':'lamp'}]))
        args = SimpleNamespace(from_batch=str(previous),state=str(self.base/'batch'),batch='test',apps='core',hotfix_manifest=None,plan_file=None)
        with patch.object(module.boto3,'Session') as session:
            with self.assertRaisesRegex(ValueError,'Unknown apps'):
                module.prepare(args)
        session.assert_not_called()

    def test_adapter_rejects_executing_bytes_outside_declared_main(self):
        with patch.object(module.subprocess,'run') as ancestry,patch.object(module.subprocess,'check_output',return_value=b'other source'):
            with self.assertRaisesRegex(ValueError,'differs from committed main'):
                module.verify_controller_source(self.data,self.manifest)
        self.assertEqual(ancestry.call_args.args[0][-1],'refs/heads/main')

    def test_prepare_uses_selected_fresh_source_and_frozen_delivery(self):
        previous=self.base/'previous'; previous.mkdir()
        old={'region':'us-east-1','account':'account','subnet':'subnet-test','worker_ami':'ami-worker'}
        (previous/'resources.json').write_text(json.dumps(old))
        (previous/'lamp-state.json').write_text(json.dumps({'ami':'ami-retired','boot_verified':True}))
        rows=[{'app':'core','source_ami':'ami-unselected','product_id':'other'},
              {'app':'lamp','source_ami':'ami-123','product_id':'product','marketplace_regions':['us-east-1'],
               'old_version':'19.0','delivery':{'Id':'old','Instructions':{'Usage':'frozen'}}}]
        plan=self.base/'plan.json';plan.write_text(json.dumps(rows))
        args=SimpleNamespace(from_batch=str(previous),state=str(self.base/'prepared'),batch='test',apps='lamp',
                             hotfix_manifest=str(self.manifest),plan_file=str(plan),cloudtask_root=None,workers=1,
                             sandbox='existing',python2='/fixture/python2',cloudtask='/fixture/cloudtask',pylib='/fixture/pylib')
        sts,ec2,catalog=Mock(),Mock(),Mock()
        sts.get_caller_identity.return_value={'Account':'account'}
        ec2.describe_images.return_value={'Images':[{'OwnerId':'account','State':'available','RootDeviceName':'/dev/sda1','BlockDeviceMappings':[{'DeviceName':'/dev/sda1','Ebs':{'SnapshotId':'snap-123'}}]}]}
        catalog.describe_entity.return_value={'DetailsDocument':{'Description':{'Visibility':'Public'},'Versions':[
            {'VersionTitle':'19.0','DeliveryOptions':[rows[1]['delivery']]},
            {'VersionTitle':'19.0.20261104','DeliveryOptions':[{'Id':'unselected'}]}]}}
        session=Mock();session.client.side_effect=lambda name: {'sts':sts,'ec2':ec2,'marketplace-catalog':catalog}[name]
        ec2.import_key_pair.side_effect=RuntimeError('stop before paid allocation')
        def keygen(args,**kwargs):
            if args[0]=='sbx':return
            if args[0]!='ssh-keygen':raise AssertionError(args)
            target=Path(args[-1]);target.write_text('test key');target.with_suffix('.pub').write_text('test public key')
        with patch.object(module.boto3,'Session',return_value=session),patch.object(module.subprocess,'run',side_effect=keygen),patch.object(module,'verify_controller_source'):
            with self.assertRaisesRegex(RuntimeError,'stop before paid'):
                module.prepare(args)
        self.assertEqual(ec2.describe_images.call_args.kwargs['ImageIds'],['ami-123'])
        self.assertEqual(catalog.describe_entity.call_count,1)
        prepared=json.loads((self.base/'prepared/plan.json').read_text())
        self.assertEqual(len(prepared),1)
        self.assertEqual(prepared[0]['source_ami'],'ami-123')
        self.assertEqual(prepared[0]['delivery'],rows[1]['delivery'])
        self.assertEqual(prepared[0]['version'],'19.0.3')
        ec2.run_instances.assert_not_called()

    def test_watch_distinguishes_available_from_customer_verified_and_scopes_apps(self):
        refresh=module.Refresh.__new__(module.Refresh)
        refresh.state=self.base;refresh.rows=[{'app':'core'},{'app':'lamp'}];refresh.hotfix=self.data
        refresh.args=SimpleNamespace(apps='lamp',watch_hours=0,poll_seconds=0)
        refresh.log=Mock();refresh.publish=Mock()
        item={'app':'lamp','boot_verified':True,'publication_status':'SUCCEEDED','visibility':'Public'}
        (self.base/'lamp-state.json').write_text(json.dumps(item))
        def reconcile(item):item.update(new_delivery_public=True,customer_verified=False)
        refresh.reconcile=Mock(side_effect=reconcile)
        with self.assertRaisesRegex(TimeoutError,'review is still pending'):
            refresh.watch_publication()
        report=json.loads((self.base/'publication-watch.json').read_text())
        self.assertEqual(report['available'],['lamp'])
        self.assertEqual(report['completed'],[])
        self.assertEqual(report['pending'],['lamp'])
        self.assertEqual(refresh.publish.call_count,1)

    def refresh_state(self, action):
        resources={'batch':'test','region':'us-east-1','account':'account','workers':[{'id':'i-worker'}],
                   'hotfix_manifest':self.manifest.name,'hotfix_manifest_sha256':module.hotfix.sha(self.manifest)}
        (self.base/'resources.json').write_text(json.dumps(resources))
        (self.base/'plan.json').write_text(json.dumps([{'app':'lamp'}]))
        return SimpleNamespace(action=action,state=str(self.base),apps=None,workers=1)

    def test_resumed_mutating_phases_recheck_main_before_aws(self):
        for action in ['run','publish','watch']:
            with self.subTest(action=action):
                args=self.refresh_state(action)
                with patch.object(module,'verify_controller_source',side_effect=ValueError('changed source')) as verify,patch.object(module.boto3,'Session') as aws:
                    with self.assertRaisesRegex(ValueError,'changed source'):
                        module.Refresh(args)
                verify.assert_called_once()
                aws.assert_not_called()

    def test_cleanup_remains_usable_with_missing_frozen_assets_or_source(self):
        args=self.refresh_state('cleanup');args.apps='mistyped';args.workers=None
        self.manifest.unlink()
        session=Mock();session.client.return_value.get_caller_identity.return_value={'Account':'account'}
        with patch.object(module.hotfix,'load',side_effect=AssertionError('cleanup cannot require hotfix assets')),patch.object(module,'verify_controller_source',side_effect=AssertionError('cleanup cannot require matching source')),patch.object(module.boto3,'Session',return_value=session):
            refresh=module.Refresh(args)
            refresh.finish_pool.shutdown()
        self.assertIsNone(refresh.hotfix)
        self.assertEqual(refresh.rows,[{'app':'lamp'}])

    def test_failed_export_resumes_same_verified_patch_without_reinstalling(self):
        refresh=module.Refresh.__new__(module.Refresh)
        first={'id':'i-first','ip':'192.0.2.1','az':'us-east-1a'}
        second={'id':'i-second','ip':'192.0.2.2','az':'us-east-1a'}
        refresh.hotfix=self.data;refresh.hotfix_path=self.manifest;refresh.state=self.base;refresh.batch='test'
        refresh.resources={'account':'account','workers':[first,second]};refresh.log=Mock();refresh.ec2=Mock()
        refresh.ec2.describe_images.return_value={'Images':[{'OwnerId':'account','State':'available','RootDeviceName':'/dev/sda1','BlockDeviceMappings':[{'DeviceName':'/dev/sda1','Ebs':{'SnapshotId':'snap-123'}}]}]}
        refresh.ec2.create_volume.return_value={'VolumeId':'vol-123'}
        refresh.ec2.create_snapshot.return_value={'SnapshotId':'snap-new'}
        attached=[False]
        refresh.ec2.attach_volume.side_effect=lambda **kwargs:attached.__setitem__(0,True)
        refresh.volume=lambda vid:{'State':'in-use' if attached[0] else 'available','Attachments':[{'State':'attached','InstanceId':first['id']}] if attached[0] else []}
        def cloudtask(*args):(self.base/'lamp.log').write_text('REFRESH_VERIFIED app=lamp')
        refresh.cloudtask=Mock(side_effect=cloudtask)
        refresh.collect_profile=Mock(side_effect=[OSError('interrupted export'),{'root_marker_sha256':'marker','profile_sha256':'profile'}])
        row={'app':'lamp','source_ami':'ami-123','version':'19.0.3'}
        with self.assertRaisesRegex(OSError,'interrupted export'):
            refresh.patch(row,first)
        saved=json.loads((self.base/'lamp-state.json').read_text())
        self.assertTrue(saved['patch_complete'])
        refresh.ec2.create_snapshot.assert_not_called()
        saved['status']='ERROR';(self.base/'lamp-state.json').write_text(json.dumps(saved));attached[0]=False
        result=refresh.patch(row,second)
        self.assertEqual(result['snapshot'],'snap-new')
        self.assertEqual(refresh.cloudtask.call_count,1)
        self.assertEqual(refresh.ec2.create_volume.call_count,1)
        self.assertEqual(refresh.ec2.attach_volume.call_count,1)
        self.assertEqual(refresh.collect_profile.call_args.args[1],first)
        refresh.ec2.detach_volume.assert_not_called()

    def test_unverified_partial_patch_requires_explicit_restart(self):
        refresh=module.Refresh.__new__(module.Refresh)
        refresh.hotfix=self.data;refresh.hotfix_path=self.manifest;refresh.state=self.base;refresh.ec2=Mock()
        row={'app':'lamp','source_ami':'ami-123'}
        refresh.cloudtask=Mock()
        for status in [None, 'PATCHING', 'ERROR', 'UNKNOWN', 'PROFILE_EXPORT_PENDING']:
            with self.subTest(status=status):
                item={**row,'volume':'vol-123'}
                if status is not None:item['status']=status
                (self.base/'lamp-state.json').write_text(json.dumps(item))
                with self.assertRaisesRegex(RuntimeError,'explicitly restart'):
                    refresh.patch(row,{'id':'i-worker'})
        self.assertEqual(refresh.ec2.mock_calls,[])
        refresh.cloudtask.assert_not_called()

    def test_verified_patch_boundary_resumes_even_if_status_was_not_updated(self):
        refresh=module.Refresh.__new__(module.Refresh)
        refresh.hotfix=self.data;refresh.hotfix_path=self.manifest;refresh.state=self.base;refresh.ec2=Mock()
        original={'id':'i-original','ip':'192.0.2.1'}
        refresh.resources={'workers':[original]}
        refresh.complete_patch=Mock(return_value='resumed verified export')
        row={'app':'lamp','source_ami':'ami-123'}
        item={**row,'volume':'vol-123','status':'PATCHING','patch_complete':True,
              'worker':original['id'],'hotfix_manifest_sha256':module.hotfix.sha(self.manifest)}
        (self.base/'lamp-state.json').write_text(json.dumps(item))
        self.assertEqual(refresh.patch(row,{'id':'i-other'}),'resumed verified export')
        refresh.complete_patch.assert_called_once_with(row,item,original)
        self.assertEqual(refresh.ec2.mock_calls,[])

    def test_invalid_export_never_poison_retained_profile_and_retry_is_immutable(self):
        refresh=module.Refresh.__new__(module.Refresh)
        refresh.hotfix=self.data;refresh.hotfix_path=self.manifest;refresh.state=self.base;refresh.batch='test'
        identity='turnkey-lamp-19.0.3.12-trixie-amd64'
        profile=b'sealed profile';packages=b'package baseline'
        receipt={'identity':identity,'pristine':True,'manifest_sha256':module.hotfix.sha(self.manifest),
                 'source_ami':'ami-123','profile_sha256':hashlib.sha256(profile).hexdigest(),
                 'packages_sha256':hashlib.sha256(packages).hexdigest()}
        def export(body):
            stream=io.BytesIO()
            with tarfile.open(fileobj=stream,mode='w:gz') as archive:
                for name,value in [(identity+'.tar.gz',body),('packages.tsv',packages),('profile-receipt.json',json.dumps(receipt).encode())]:
                    entry=tarfile.TarInfo(name);entry.size=len(value);archive.addfile(entry,io.BytesIO(value))
            return SimpleNamespace(returncode=0,stdout=module.base64.b64encode(stream.getvalue()).decode())
        refresh.ssh=Mock(return_value=export(b'corrupt bytes'))
        row={'app':'lamp','source_ami':'ami-123'}
        with self.assertRaisesRegex(ValueError,'binding differs'):
            refresh.collect_profile(row,{'ip':'192.0.2.1'})
        self.assertEqual(list((self.base/'profiles/lamp').iterdir()),[])
        refresh.ssh.return_value=export(profile)
        result=refresh.collect_profile(row,{'ip':'192.0.2.1'})
        self.assertEqual(result['profile_sha256'],receipt['profile_sha256'])
        sealed=(self.base/'profiles/lamp'/ (identity+'.tar.gz')).read_bytes()
        self.assertEqual(refresh.collect_profile(row,{'ip':'192.0.2.1'}),result)
        self.assertEqual((self.base/'profiles/lamp'/ (identity+'.tar.gz')).read_bytes(),sealed)
        receipt['profile_sha256']=hashlib.sha256(b'different valid candidate').hexdigest()
        refresh.ssh.return_value=export(b'different valid candidate')
        with self.assertRaisesRegex(ValueError,'Existing profile export differs'):
            refresh.collect_profile(row,{'ip':'192.0.2.1'})
        self.assertEqual((self.base/'profiles/lamp'/ (identity+'.tar.gz')).read_bytes(),sealed)

    def test_legacy_reconcile_does_not_require_hotfix_region_receipt(self):
        refresh=module.Refresh.__new__(module.Refresh);refresh.state=self.base;refresh.hotfix=None;refresh.batch='test'
        refresh.args=SimpleNamespace(customer_acceptance=None);refresh.catalog=Mock()
        refresh.catalog.describe_change_set.return_value={'Status':'SUCCEEDED'}
        refresh.catalog.describe_entity.return_value={'DetailsDocument':{'Description':{'Visibility':'Public'},'Versions':[
            {'VersionTitle':'19.0','DeliveryOptions':[{'Id':'old','Visibility':'Public'}]},
            {'VersionTitle':'19.0.20261104','DeliveryOptions':[{'Id':'new','Visibility':'Public'}]}]}}
        item={'app':'lamp','version':'19.0.20261104','product_id':'product','change_set_id':'change'}
        with patch.object(module,'qa_receipt',side_effect=AssertionError('legacy has no hotfix QA contract')):
            refresh.reconcile(item)
        self.assertTrue(item['new_delivery_public'])
        self.assertFalse(item['customer_verified'])
        refresh.catalog.start_change_set.assert_not_called()

    def test_legacy_watch_completes_aws_publication_without_claiming_customer_qa(self):
        refresh=module.Refresh.__new__(module.Refresh);refresh.state=self.base;refresh.hotfix=None
        refresh.rows=[{'app':'lamp'}];refresh.args=SimpleNamespace(apps=None,watch_hours=0,poll_seconds=0)
        refresh.log=Mock();refresh.publish=Mock()
        (self.base/'lamp-state.json').write_text(json.dumps({'app':'lamp','boot_verified':True,'publication_status':'SUCCEEDED','visibility':'Public'}))
        def reconcile(item):item.update(new_delivery_public=True,customer_verified=False,retirement_status='NOT_REQUESTED')
        refresh.reconcile=Mock(side_effect=reconcile)
        refresh.watch_publication()
        report=json.loads((self.base/'publication-watch.json').read_text())
        self.assertEqual(report['completed'],['lamp'])
        self.assertEqual(report['available'],['lamp'])
        self.assertEqual(report['completion_scope'],'aws-publication')

    def test_customer_receipt_requires_matching_delivery_and_all_regions(self):
        evidence = self.base/'qa.log'; evidence.write_text('actual launch evidence')
        proof = {'result':'PASS','source_ami':'ami-new','version':'19.0.3','delivery_ids':['new'],
                 'regions':{'us-east-1':{'result':'PASS','customer_ami':'ami-customer','launch_instance':'i-test'}},
                 'evidence':[{'path':'qa.log','sha256':module.hotfix.sha(evidence)}]}
        path=self.base/'qa.json'; path.write_text(json.dumps({'lamp':proof}))
        item={'app':'lamp','ami':'ami-new','version':'19.0.3','new_delivery_ids':['new'],'marketplace_regions':['us-east-1']}
        self.assertTrue(module.qa_receipt(path,item,customer=True))
        item['marketplace_regions'].append('eu-west-1')
        with self.assertRaisesRegex(ValueError,'region coverage'):
            module.qa_receipt(path,item,customer=True)
        item['marketplace_regions']=['us-east-1']; proof['delivery_ids']=['old'];path.write_text(json.dumps({'lamp':proof}))
        with self.assertRaisesRegex(ValueError,'different delivery'):
            module.qa_receipt(path,item,customer=True)


if __name__ == '__main__':
    unittest.main()
