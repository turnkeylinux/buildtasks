"""Run the EC2 account-selection hook against private first-boot fixtures."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "patches/ec2/overlay/usr/lib/inithooks/firstboot.d/28ec2-sudoadmin"
REFRESH = ROOT / "bin/refresh-ec2-rootfs"


class EC2SudoAdminTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.defaults = self.root / "inithooks"
        self.version = self.root / "turnkey_version"
        self.server = self.root / "server.conf"
        self.hook = self.root / "28ec2-sudoadmin"
        source = HOOK.read_text()
        for old, new in (
            ("/etc/default/inithooks", self.defaults),
            ("/etc/turnkey_version", self.version),
            ("/var/lib/hubclient/server.conf", self.server),
        ):
            source = source.replace(old, str(new))
        self.hook.write_text(source)

    def run_hook(self, release="19.1-trixie", hub=True, selected="true", interactive=False):
        self.version.write_text("turnkey-wordpress-" + release + "-amd64\n")
        self.defaults.write_text("RUN_FIRSTBOOT=true\nSUDOADMIN=" + selected + "\n")
        if hub:
            self.server.write_text("SERVERID=fixture-server\n")
        env = {key: value for key, value in os.environ.items() if key != "_TURNKEY_INIT"}
        if interactive:
            env["_TURNKEY_INIT"] = "1"
        result = subprocess.run(["bash", str(self.hook)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.defaults.read_text()

    def test_trixie_hub_preserves_admin_default(self):
        self.assertIn("SUDOADMIN=true\n", self.run_hook())

    def test_trixie_hub_preserves_explicit_root_selection(self):
        self.assertIn("SUDOADMIN=false\n", self.run_hook(selected="false"))

    def test_trixie_non_hub_preserves_selection(self):
        for selected in ("true", "false"):
            with self.subTest(selected=selected):
                self.assertIn("SUDOADMIN=" + selected + "\n", self.run_hook(hub=False, selected=selected))

    def test_bookworm_hub_retains_root_default(self):
        self.assertIn("SUDOADMIN=false\n", self.run_hook(release="18.0-bookworm"))

    def test_bookworm_non_hub_preserves_admin_selection(self):
        self.assertIn("SUDOADMIN=true\n", self.run_hook(release="18.0-bookworm", hub=False))

    def test_interactive_setup_preserves_selection(self):
        self.assertIn("SUDOADMIN=true\n", self.run_hook(release="18.0-bookworm", interactive=True))


@unittest.skipUnless(os.geteuid() == 0 and Path('/usr/sbin/sshd').is_file(),
                     'requires an isolated root fixture with Debian OpenSSH')
class EC2SSHPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dropins = self.root / 'etc/ssh/sshd_config.d'
        self.dropins.mkdir(parents=True)
        self.config = self.root / 'etc/ssh/sshd_config'
        self.policy = self.dropins / '00-turnkey-aws-marketplace.conf'
        self.key = self.root / 'host_key'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '',
                        '-f', str(self.key)], check=True, capture_output=True)
        Path('/run/sshd').mkdir(exist_ok=True)
        self.base = ('HostKey ' + str(self.key) + '\nInclude ' + str(self.dropins) +
                     '/*.conf\nKbdInteractiveAuthentication no\nPermitRootLogin no\n')
        self.config.write_text(self.base)
        (self.dropins / 'turnkey.conf').write_text(
            'PermitRootLogin yes\nMatch user root\nMatch user *\n')

    def effective(self, user):
        output = subprocess.check_output([
            '/usr/sbin/sshd', '-T', '-f', str(self.config), '-C',
            'user=' + user + ',host=localhost,addr=127.0.0.1'], text=True)
        return dict(line.split(' ', 1) for line in output.splitlines())

    def apply_policy(self):
        source = REFRESH.read_text()
        start = source.index('# Older EC2 conversions lack the canonical')
        end = source.index('[[ -z $(chroot "$root" dpkg --audit) ]]', start)
        # Exercise the actual helper block against private paths. The wrapper
        # supplies sshd's config path instead of constructing a second rootfs.
        wrapper = '''set -euo pipefail
root=$1
chroot() {
    [[ $1 == "$root" && $2 == /usr/sbin/sshd ]]
    shift 2
    /usr/sbin/sshd -f "$root/etc/ssh/sshd_config" "$@"
}
'''
        return subprocess.run(['bash', '-c', wrapper + source[start:end],
                               '--', str(self.root)], capture_output=True, text=True)

    def canonical(self):
        return ('PasswordAuthentication no\nKbdInteractiveAuthentication no\n'
                'PermitRootLogin no\nPubkeyAuthentication yes\n')

    def test_legacy_conversion_gets_effective_key_only_policy(self):
        self.assertEqual(self.effective('admin')['passwordauthentication'], 'yes')
        self.assertEqual(self.effective('root')['permitrootlogin'], 'yes')
        original = self.config.read_bytes()
        result = self.apply_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.policy.read_text(), self.canonical())
        self.assertEqual(self.policy.stat().st_mode & 0o777, 0o644)
        self.assertEqual((self.policy.stat().st_uid, self.policy.stat().st_gid), (0, 0))
        self.assertEqual(self.config.read_bytes(), original)
        admin = self.effective('admin')
        self.assertEqual(admin['passwordauthentication'], 'no')
        self.assertEqual(admin['kbdinteractiveauthentication'], 'no')
        self.assertEqual(admin['pubkeyauthentication'], 'yes')
        self.assertEqual(self.effective('root')['permitrootlogin'], 'no')

    def test_existing_canonical_policy_is_preserved(self):
        self.policy.write_text('# Retain the existing file\n' + self.canonical() +
                               'AuthenticationMethods publickey\n')
        self.policy.chmod(0o640)
        before = (self.policy.read_bytes(), self.policy.stat())
        result = self.apply_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        after = self.policy.stat()
        self.assertEqual(self.policy.read_bytes(), before[0])
        for attribute in ('st_mode', 'st_uid', 'st_gid', 'st_ino', 'st_mtime_ns'):
            self.assertEqual(getattr(after, attribute), getattr(before[1], attribute))
        self.assertEqual(self.effective('admin')['authenticationmethods'], 'publickey')

    def test_existing_weak_policy_is_rejected_without_overwriting(self):
        self.policy.write_text(self.canonical().replace('PasswordAuthentication no',
                                                       'PasswordAuthentication yes'))
        before = self.policy.read_bytes()
        self.assertNotEqual(self.apply_policy().returncode, 0)
        self.assertEqual(self.policy.read_bytes(), before)

    def test_earlier_global_override_is_rejected(self):
        self.config.write_text('PermitRootLogin yes\n' + self.base)
        self.assertNotEqual(self.apply_policy().returncode, 0)

    def test_admin_match_override_is_rejected(self):
        self.config.write_text(self.base + 'Match User admin\nPasswordAuthentication yes\n')
        self.assertNotEqual(self.apply_policy().returncode, 0)

    def test_root_match_override_is_rejected(self):
        self.config.write_text(self.base + 'Match User root\nPermitRootLogin yes\n')
        self.assertNotEqual(self.apply_policy().returncode, 0)


if __name__ == "__main__":
    unittest.main()
