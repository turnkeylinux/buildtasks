"""Run the EC2 account-selection hook against private first-boot fixtures."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "patches/ec2/overlay/usr/lib/inithooks/firstboot.d/28ec2-sudoadmin"


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


if __name__ == "__main__":
    unittest.main()
