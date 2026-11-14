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
        self.data = {'release': '19.0.3', 'technical_release': '19.0.3.3', 'release_notes': 'Current maintenance fixes.',
                     'sources': {name: self.commit for name in ['buildtasks_main', 'common_main', 'release_main', 'controller_main']},
                     'packages': {name: {'version': '1.0', 'sha256': 'b'*64, 'source_main': self.commit} for name in module.hotfix.PACKAGES},
                     'minimum_packages': {'hubdns': '1.5.0', 'hubclient': '0.3.0', 'webmin': '2.660.turnkey0'},
                     'profile_generator': asset('generator'), 'aptconf_tag': asset('apt-tag'),
                     'apps': {'lamp': {'source_ami': 'ami-123', 'source_snapshot': 'snap-123', 'source_main': self.commit,
                                      'identity_package': asset('identity.deb'), 'superseded_delivery_ids': ['old'],
                                      'profile_conf': {'core': asset('conf/core'), 'lamp': asset('conf/lamp'),
                                                       'hooks/lamp/50-export': {**asset('conf/hook'), 'mode': 0o755}}}}}
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

    def factory(self):
        root = self.base / 'root'
        for name in ['etc/default', 'etc/webmin', 'run', 'var/lib/turnkey-info']:
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / 'etc/default/inithooks').write_text('RUN_FIRSTBOOT=true\n')
        (root / 'etc/webmin/miniserv.conf').write_text('port=12321\ncustom=value\n')
        (root / 'etc/turnkey_version').write_text('turnkey-lamp-19.0.3.3-trixie-amd64\n')
        (root / 'var/lib/turnkey-info/hotfix.json').write_text('{}')
        return root

    def test_initialized_root_is_refused(self):
        root = self.factory()
        (root / 'etc/default/inithooks').write_text('RUN_FIRSTBOOT=false\n')
        with self.assertRaisesRegex(ValueError, 'completed setup'):
            module.hotfix.factory(root)

    def test_package_install_checks_signed_candidate_before_installing(self):
        root = self.factory()
        def command(args):
            if 'apt-cache' in args:
                return 'SHA256: ' + 'c'*64
            raise AssertionError(args)
        with patch.object(module.hotfix, 'run', side_effect=command) as runner:
            with self.assertRaisesRegex(ValueError, 'signed APT candidate hash'):
                module.hotfix.install(root, self.manifest, 'lamp')
        self.assertFalse(any('apt-get' in c.args[0] for c in runner.call_args_list))

    def install(self, root):
        calls=[]
        def command(args):
            args=list(map(str,args)); calls.append(args)
            if 'apt-cache' in args:return 'SHA256: '+'b'*64
            if 'dpkg-query' in args:
                if args[-1]=='-f=${Package}\n':return 'turnkey-lamp-19.0'
                return self.data['minimum_packages'].get(args[-1],'1.0')
            if args[0]=='dpkg-deb':return 'turnkey-lamp-19.0.3.3' if args[-1]=='Package' else '1'
            return ''
        with patch.object(module.hotfix,'run',side_effect=command):
            module.hotfix.install(root,self.manifest,'lamp')
        return calls

    def test_install_preserves_settings_and_uses_only_frozen_package_targets(self):
        root=self.factory(); calls=self.install(root)
        config=(root/'etc/webmin/miniserv.conf').read_text()
        self.assertIn('custom=value\n',config)
        self.assertIn('extracas=/etc/ssl/private/cert.pem\n',config)
        self.assertEqual((root/'etc/turnkey_version').read_text(),'turnkey-lamp-19.0.3.3-trixie-amd64\n')
        apt=next(args for args in calls if 'apt-get' in args)
        self.assertEqual(set(apt[apt.index('install')+1:]),{name+'=1.0' for name in module.hotfix.PACKAGES})
        self.assertIn('APT::Get::AllowUnauthenticated=false',apt)
        self.assertTrue(any('--purge' in args and 'turnkey-lamp-19.0' in args for args in calls))

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

    def test_profile_uses_final_readonly_root_and_retains_hook_mode(self):
        root = self.factory(); output = self.base / 'output'; calls = []
        def command(args):
            args = list(map(str, args)); calls.append(args)
            if '/usr/lib/tklbam-pypy2/bin/pypy' in args:
                work = next((root / 'run').glob('ec2-profile-*')) / 'work'
                self.assertEqual((work/'profile-conf/hooks/lamp/50-export').stat().st_mode & 0o777, 0o755)
                (output / 'turnkey-lamp-19.0.3.3-trixie-amd64.tar.gz').write_bytes(b'generated profile')
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
        identity='turnkey-lamp-19.0.3.3-trixie-amd64'
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
