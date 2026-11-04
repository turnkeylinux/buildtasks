"""Exercise interactive, automated and incomplete container logins."""
import os
from pathlib import Path
import pty
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'patches/container/overlay/root/.profile.d/turnkey-init-fence'


class ContainerLoginTest(unittest.TestCase):
    def login(self, interactive=True, startup=0, pending=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'systemctl').write_text(
                '#!/bin/sh\necho "$*" >> "$CALLS"\n'
                'case "$1" in start) exit "$STARTUP";; is-enabled) exit "$PENDING";; esac\n')
            (root / 'dtach').write_text('#!/bin/sh\necho SETUP >> "$CALLS"\n')
            for name in ('systemctl', 'dtach'):
                (root / name).chmod(0o755)
            profile = root / 'profile'
            profile.write_text(PROFILE.read_text().replace('/usr/bin/dtach', str(root / 'dtach')))
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                       CALLS=str(root / 'calls'), STARTUP=str(startup),
                       PENDING='0' if pending else '1')
            master, slave = pty.openpty()
            try:
                result = subprocess.run(['bash', '--noprofile', '--norc',
                                         '-ic' if interactive else '-c', '. "$1"', 'test', str(profile)],
                                        env=env, stdin=slave, stdout=slave,
                                        stderr=subprocess.PIPE, timeout=5)
            finally:
                os.close(master)
                os.close(slave)
            return (root / 'calls').read_text().splitlines() if (root / 'calls').exists() else []

    def test_first_login_waits_for_boot_and_opens_setup(self):
        self.assertEqual(self.login(), ['start inithooks.service',
                         'is-enabled --quiet turnkey-init-fence.service', 'SETUP',
                         'is-enabled --quiet turnkey-init-fence.service'])

    def test_noninteractive_ssh_does_not_open_setup_even_with_tty(self):
        self.assertEqual(self.login(interactive=False), [])

    def test_boot_failure_does_not_race_setup(self):
        self.assertEqual(self.login(startup=1), ['start inithooks.service'])

    def test_unattended_completion_does_not_repeat_setup(self):
        self.assertEqual(self.login(pending=False), ['start inithooks.service',
                         'is-enabled --quiet turnkey-init-fence.service'])


if __name__ == '__main__':
    unittest.main()
