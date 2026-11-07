"""Exercise fresh-container presets with the real systemctl offline interface."""
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / 'patches/container/conf'
WAITER = 'systemd-networkd-wait-online.service'


class ContainerNetworkPresetTest(unittest.TestCase):
    def preset(self, masked):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            units = root / 'usr/lib/systemd/system'
            units.mkdir(parents=True)
            for name in ('systemd-networkd.service', WAITER):
                target = 'network-online.target' if name == WAITER else 'multi-user.target'
                (units / name).write_text(
                    '[Service]\nExecStart=/bin/true\n[Install]\nWantedBy=' + target + '\n')
            vendor = root / 'usr/lib/systemd/system-preset'
            vendor.mkdir(parents=True)
            (vendor / '90-default.preset').write_text('enable *\n')
            presets = root / 'etc/systemd/system-preset'
            presets.mkdir(parents=True)
            # PVE disables networkd, but leaves its separately installable waiter.
            (presets / '00-pve.preset').write_text('disable systemd-networkd.service\n')
            if masked:
                command = next(line for line in CONF.read_text().splitlines()
                               if line == 'systemctl mask ' + WAITER)
                self.systemctl(root, *shlex.split(command)[1:])
            self.systemctl(root, 'preset-all')
            mask = root / 'etc/systemd/system' / WAITER
            enabled = root / 'etc/systemd/system/network-online.target.wants' / WAITER
            return mask.is_symlink() and mask.readlink() == Path('/dev/null'), enabled.is_symlink()

    def systemctl(self, root, *arguments):
        subprocess.run(['systemctl', '--root=' + str(root), *arguments],
                       check=True, capture_output=True, text=True, timeout=5)

    def test_first_boot_presets_enable_old_waiter_but_preserve_container_mask(self):
        self.assertEqual(self.preset(masked=False), (False, True))
        self.assertEqual(self.preset(masked=True), (True, False))


if __name__ == '__main__':
    unittest.main()
