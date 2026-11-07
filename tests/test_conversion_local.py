"""Exercise CLI refusals and mocked population without disks, AWS or signing."""
import importlib.util
import os
import runpy
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_bundle():
    spec = importlib.util.spec_from_file_location('local_bundle_test', ROOT/'bin/ec2/ebs_bundle.py')
    module = importlib.util.module_from_spec(spec)
    # AWS imports are inert test doubles; any call is a test failure below.
    utils = types.ModuleType('utils')
    utils.get_logger = Mock(return_value=Mock())
    utils.connect = Mock(side_effect=AssertionError('Unexpected AWS lifecycle call'))
    utils.rsync = Mock()
    utils.is_mounted = Mock(return_value=False)
    utils.mkdir = Mock()
    with patch.dict(sys.modules, {'utils': utils}):
        spec.loader.exec_module(module)
    return module, utils


class LocalCliTest(unittest.TestCase):
    def test_invalid_options_fail_before_config_or_setup(self):
        # A private copy has no config/bin helpers; reaching those would be a failure.
        with tempfile.TemporaryDirectory() as d:
            script = Path(d)/'bt-ec2'
            script.write_bytes((ROOT/'bt-ec2').read_bytes())
            cases = [
                (['--local-device='], 'empty local device'),
                (['--local-device=/missing'], '--local-device requires --testing'),
                (['--testing', '--local-device=/missing'], 'local device is not a block device'),
                (['--testing', '--local-device=/missing', '--local-device=/other'], 'duplicate --local-device'),
                *[(['--testing', '--local-device=/missing', flag], '--local-device conflicts with')
                  for flag in ('--publish','--copy','--marketplace','--pvmregister','--pvmshim','--name=unused','--force')],
                (['--unknown'], 'unknown option: --unknown'),
            ]
            for options,message in cases:
                with self.subTest(options=options):
                    result = subprocess.run(['bash','-e',str(script),*options,'prestashop-19.0-trixie-amd64'], capture_output=True,text=True)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn(message, result.stderr)
                    self.assertNotIn('common.cfg', result.stderr)
                    self.assertNotIn('No such file', result.stderr)

    def test_positive_cli_checks_before_extraction_and_dispatches_local_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            bt=root/'buildtasks'; (bt/'bin/ec2').mkdir(parents=True)
            (bt/'config').mkdir()
            fakebin=root/'commands'; fakebin.mkdir()
            calls=root/'calls'
            device=root/'fake-block-device'; device.touch()
            script=bt/'bt-ec2'
            source=(ROOT/'bt-ec2').read_text()
            # Stub only the shell's physical block-node predicate. The complete
            # real option grammar, sequencing and final dispatch are unchanged.
            self.assertEqual(source.count('[[ -b "$local_device" ]]'),1)
            script.write_text(source.replace('[[ -b "$local_device" ]]','[[ -f "$local_device" ]]'))
            (bt/'config/common.cfg').write_text('export BT_BUILDS="'+str(root/'builds')+'"\nexport BT_ISOS="'+str(root/'isos')+'"\n')
            (bt/'config/aws.cfg').write_text('echo AWS_CONFIG_MUST_NOT_RUN >&2; exit 99\n')
            stub='''#!/bin/bash
set -e
name=$(basename "$0")
printf '%s %s\n' "$name" "$*" >> "$CALLS"
case "$name" in
 git) echo fixturecommit ;;
 turnkey-version) if [[ " $* " == *" -a "* ]]; then echo 'prestashop 19.0 trixie amd64'; else echo 19; fi ;;
 dpkg) echo amd64 ;;
 grep|netstat) exit 1 ;;
 tklpatch-extract-iso) mkdir -p turnkey-prestashop-19.0-trixie-amd64.rootfs/{dev,sys,proc} ;;
 generate-buildenv) echo fixture-buildenv ;;
 ebs_populate.py) if [[ ${FAIL_DEVICE_CHECK:-} == 1 && $1 == --check-device ]]; then echo UNSUPPORTED_DEVICE_TYPE >&2; exit 42; fi ;;
 aws-setup|ec2-setup|ebs.py) echo AWS_LIFECYCLE_MUST_NOT_RUN >&2; exit 99 ;;
esac
'''
            for name in ('git','turnkey-version','dpkg','grep','netstat','mount','umount','tklpatch-extract-iso','tklpatch-apply'):
                path=fakebin/name; path.write_text(stub); path.chmod(0o755)
            for name in ('iso-download','iso-verify','purge-pkgs','rootfs-cleanup','aptconf-tag','build-tag','generate-buildenv','aws-setup','ec2-setup','ec2/ebs_populate.py','ec2/ebs.py'):
                path=bt/'bin'/name; path.write_text(stub); path.chmod(0o755)
            env=dict(os.environ,PATH=str(fakebin)+':'+os.environ['PATH'],CALLS=str(calls))
            result=subprocess.run(['bash','-e',str(script),'--testing','--local-device='+str(device),'prestashop-19.0-trixie-amd64'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            lines=calls.read_text().splitlines()
            check='ebs_populate.py --check-device '+str(device)
            populate='ebs_populate.py turnkey-prestashop-19.0-trixie-amd64.rootfs '+str(device)
            self.assertIn(check,lines)
            self.assertIn(populate,lines)
            extract=next(i for i,line in enumerate(lines) if line.startswith('tklpatch-extract-iso '))
            self.assertLess(lines.index(check),extract)
            self.assertGreater(lines.index(populate),extract)
            self.assertFalse(any(line.startswith(('aws-setup ','ec2-setup ','ebs.py ')) for line in lines))
            calls.write_text('')
            result=subprocess.run(['bash','-e',str(script),'--testing','--local-device='+str(device),'prestashop-19.0-trixie-amd64'],env=dict(env,FAIL_DEVICE_CHECK='1'),capture_output=True,text=True)
            self.assertEqual(result.returncode,42)
            self.assertIn('UNSUPPORTED_DEVICE_TYPE',result.stderr)
            self.assertEqual(calls.read_text().splitlines(),[check])




class DeviceTest(unittest.TestCase):
    def setUp(self):
        self.module,self.utils = load_bundle()

    def test_regular_file_refused_before_commands(self):
        m=self.module
        with patch.object(m.os, 'stat', return_value=types.SimpleNamespace(st_mode=stat.S_IFREG)), patch.object(m.subprocess,'run') as run:
            with self.assertRaises(m.EbsBundleError): m.validate_local_device('/dev/fake')
            run.assert_not_called()

    def test_non_disk_types_and_unsupported_names_refused_before_writes(self):
        m=self.module
        with patch.object(m.os,'stat',return_value=types.SimpleNamespace(st_mode=stat.S_IFBLK)), patch.object(m.subprocess,'run') as run:
            for kind in ('part','loop','lvm','crypt','raid1','rom'):
                run.return_value.stdout=kind+'\n'
                with self.subTest(kind=kind), self.assertRaisesRegex(m.EbsBundleError,'TYPE disk'):
                    m.validate_local_device('/dev/nvme1n1')
            run.return_value.stdout='disk\n'
            with self.assertRaisesRegex(m.EbsBundleError,'unsupported local whole-disk name'):
                m.validate_local_device('/dev/mmcblk0')
            self.assertTrue(all(c.args[0][:4]==['lsblk','-dn','-o','TYPE'] for c in run.call_args_list))

    def test_mounted_disk_refused_and_idle_disk_accepted(self):
        m=self.module
        with patch.object(m.os,'stat',return_value=types.SimpleNamespace(st_mode=stat.S_IFBLK)), patch.object(m.subprocess,'run') as run:
            def response(argv,**kwargs):
                return Mock(stdout='disk\n' if 'TYPE' in argv else mounts)
            run.side_effect=response
            mounts='\n/\n'
            with self.assertRaisesRegex(m.EbsBundleError,'mounted'): m.validate_local_device('/dev/nvme1n1')
            mounts='\n\n'
            self.assertEqual(m.validate_local_device('/dev/nvme1n1'),'/dev/nvme1n1')
            self.assertEqual(run.call_args.args[0],['lsblk','-nr','-o','MOUNTPOINT','/dev/nvme1n1'])

    def test_nvme_and_xvd_partition_paths(self):
        m=self.module
        for whole,partition in [('/dev/nvme1n1','/dev/nvme1n1p2'),('/dev/xvdf','/dev/xvdf2')]:
            with self.subTest(whole=whole), patch.object(m.subprocess,'run') as run, patch.object(m.time,'sleep'):
                device=m.Device(whole)
                device.mkpart()
                self.assertEqual(device.root_path,whole)
                self.assertEqual(device.real_path,partition)
                device.mkfs('ext4')
                self.assertEqual(run.call_args.args[0],['mkfs.ext4','-F','-j',partition])
        self.utils.connect.assert_not_called()

    def test_failed_grub_cleans_submounts_and_propagates(self):
        m=self.module
        device=Mock(root_path='/dev/nvme1n1')
        def run(argv, **kwargs):
            if 'grub-install' in argv: raise subprocess.CalledProcessError(1,argv)
            return Mock()
        with patch.object(m.subprocess,'run',side_effect=run) as commands, patch.object(m.os,'chmod'), patch.object(m.os.path,'isdir',return_value=True), patch.object(m.os,'rmdir') as rmdir:
            with self.assertRaises(subprocess.CalledProcessError): m.populate('/prepared',device)
            unmounts=[c.args[0][-1] for c in commands.call_args_list if c.args[0][0]=='umount']
            self.assertEqual(unmounts,['/prepared.mount/dev','/prepared.mount/proc','/prepared.mount/sys'])
            device.umount.assert_called_once()
            rmdir.assert_called_once_with('/prepared.mount')
        self.utils.connect.assert_not_called()

    def test_success_populates_without_aws(self):
        m=self.module
        device=Mock(root_path='/dev/xvdf')
        with patch.object(m.subprocess,'run') as run, patch.object(m.os,'chmod') as chmod, patch.object(m.os.path,'isdir',return_value=False):
            m.populate('/prepared',device)
            device.mkpart.assert_called_once()
            device.mkfs.assert_called_once_with('ext4')
            self.utils.rsync.assert_called_once_with('/prepared','/prepared.mount')
            chmod.assert_called_once_with('/prepared.mount',0o755)
            self.assertIn(['chroot','/prepared.mount','update-initramfs','-u'],[c.args[0] for c in run.call_args_list])
            device.umount.assert_called_once()
        self.utils.connect.assert_not_called()


class PopulationEntryTest(unittest.TestCase):
    def test_entry_validates_before_creating_device(self):
        fake=types.ModuleType('ebs_bundle')
        fake.Device=Mock()
        fake.populate=Mock()
        fake.validate_local_device=Mock(side_effect=ValueError('mounted disk'))
        with tempfile.TemporaryDirectory() as d, patch.dict(sys.modules,{'ebs_bundle':fake}), patch.object(sys,'argv',['ebs_populate.py',d,'/dev/example']):
            with self.assertRaises(ValueError):
                runpy.run_path(str(ROOT/'bin/ec2/ebs_populate.py'),run_name='__main__')
        fake.Device.assert_not_called()
        fake.populate.assert_not_called()

    def test_check_only_never_creates_or_populates_device(self):
        fake=types.ModuleType('ebs_bundle')
        fake.Device=Mock()
        fake.populate=Mock()
        fake.validate_local_device=Mock(return_value='/dev/nvme1n1')
        with patch.dict(sys.modules,{'ebs_bundle':fake}), patch.object(sys,'argv',['ebs_populate.py','--check-device','/dev/nvme1n1']):
            runpy.run_path(str(ROOT/'bin/ec2/ebs_populate.py'),run_name='__main__')
        fake.validate_local_device.assert_called_once_with('/dev/nvme1n1')
        fake.Device.assert_not_called()
        fake.populate.assert_not_called()

    def test_entry_passes_validated_whole_disk(self):
        fake=types.ModuleType('ebs_bundle')
        fake.Device=Mock()
        fake.populate=Mock()
        fake.validate_local_device=Mock(return_value='/dev/nvme1n1')
        with tempfile.TemporaryDirectory() as d, patch.dict(sys.modules,{'ebs_bundle':fake}), patch.object(sys,'argv',['ebs_populate.py',d,'/dev/disk/by-id/explicit-volume']):
            runpy.run_path(str(ROOT/'bin/ec2/ebs_populate.py'),run_name='__main__')
            fake.validate_local_device.assert_called_once_with('/dev/disk/by-id/explicit-volume')
            fake.Device.assert_called_once_with('/dev/nvme1n1')
            fake.populate.assert_called_once_with(d,fake.Device.return_value)


class HashNameTest(unittest.TestCase):
    def generate(self,name,release='debian/trixie'):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            gpg=root/'gpg'
            gpg.write_text('''#!/bin/bash
case "$*" in
    *--import*) cat >/dev/null ;;
    *--with-colons*) echo 'fpr:::::::::PUBLICFINGERPRINT:'; echo 'uid:::::::::Public fixture:' ;;
    *) echo 'Public fixture key' ;;
esac
''')
            gpg.chmod(0o755)
            keys=root/'common/keys';keys.mkdir(parents=True)
            (keys/'tkl-trixie-images.asc').write_text('public fixture key')
            (root/name).write_bytes(b'tarball-fixture')
            script=root/'generate-signature'
            script.write_text((ROOT/'bin/generate-signature').read_text().replace('/tmp/temp.gpg',str(root/'fixture-public-keyring.gpg')))
            result=subprocess.run(['bash',str(script),str(root/name)],env=dict(os.environ,PATH=str(root)+':'+os.environ['PATH'],FAB_PATH=str(root),RELEASE=release),capture_output=True,text=True)
            output=Path(str(root/name)+'.hash')
            return result,output.read_text() if output.exists() else ''

    def test_revision3_hash_uses_current_key_contract_without_signing(self):
        result,text=self.generate('debian-13-turnkey-prestashop_19.0-3_amd64.tar.gz')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('19.x/keys/tkl-trixie-images.asc',text)
        self.assertIn('release-trixie-images@turnkeylinux.org',text)
        self.assertIn('debian-13-turnkey-prestashop_19.0-3_amd64.tar.gz',text)
        self.assertNotIn('BEGIN PGP SIGNED MESSAGE',text)

    def test_mismatched_release_refused_before_key_lookup(self):
        for name in ['debian-12-turnkey-prestashop_19.0-3_amd64.tar.gz','debian-13-turnkey-prestashop_18.0-3_amd64.tar.gz','random.tar.gz']:
            result,text=self.generate(name)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(text,'')


if __name__=='__main__': unittest.main()
