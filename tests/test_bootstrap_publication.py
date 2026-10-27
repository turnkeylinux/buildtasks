#!/usr/bin/env python3
"""The setup client downloads the checksum next to the bootstrap archive."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class BootstrapPublicationTest(unittest.TestCase):
    def test_archive_and_checksum_share_the_image_destination(self):
        source = (Path(__file__).resolve().parents[1] / 'bt-bootstrap').read_text()
        block = 'if [[ "$publish" == "yes" ]]; then' + source.rsplit(
            'if [[ "$publish" == "yes" ]]; then', 1)[1].split('\nfi', 1)[0] + '\nfi\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'build'
            output.mkdir()
            filename = 'bootstrap-trixie-amd64.tar.gz'
            for suffix in ['', '.hash', '.manifest', '.buildenv']:
                (output / (filename + suffix)).write_text('fixture' + suffix)
            (root / 'bin').mkdir()
            publisher = root / 'bin/publish-files'
            publisher.write_text('#!/bin/bash\nset -e\nmkdir -p "$PUBLISH_DEST"\ncp "$@" "$PUBLISH_DEST"\n')
            publisher.chmod(0o755)
            env = dict(os.environ, publish='yes', BT=str(root), O=str(output),
                       BOOTSTRAP_TARBALL=filename, BT_PUBLISH_IMGS=str(root / 'images'),
                       BT_PUBLISH_META=str(root / 'metadata'))
            subprocess.run(['bash', '-ec', block], env=env, check=True)
            self.assertEqual((root / 'images/bootstrap' / filename).read_text(), 'fixture')
            self.assertEqual((root / 'images/bootstrap' / (filename + '.hash')).read_text(), 'fixture.hash')
            for suffix in ['.hash', '.manifest', '.buildenv']:
                self.assertEqual((root / 'metadata' / (filename + suffix)).read_text(), 'fixture' + suffix)


if __name__ == '__main__':
    unittest.main()
