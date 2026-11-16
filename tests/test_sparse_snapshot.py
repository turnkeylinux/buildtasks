import base64
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

spec = importlib.util.spec_from_file_location('sparse_snapshot', Path(__file__).resolve().parents[1]/'bin/ec2-sparse-snapshot.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SparseSnapshotTest(unittest.TestCase):
    def test_snapshot_preserves_block_indexes_and_checksums_across_zero_gaps(self):
        blocks = [(1, b'a'*(512*1024)), (9, b'b'*(512*1024))]
        stream = b''
        for index, data in blocks:
            packed = zlib.compress(data)
            stream += struct.pack('!QI', index, len(packed)) + packed
        stream += struct.pack('!QI', 2**64-1, 0)
        process = Mock(stdout=io.BytesIO(stream))
        process.wait.return_value = 0
        ebs = Mock(); ebs.start_snapshot.return_value = {'SnapshotId':'snap-new'}
        with tempfile.TemporaryDirectory() as directory, patch.object(module.subprocess, 'Popen', return_value=process):
            result = module.create_snapshot(ebs, ['ssh','worker'], 'vol-123', 1, 'test', [], Path(directory)/'state.json')
        self.assertEqual(result['uploaded_bytes'], 2*512*1024)
        calls = sorted((c.kwargs for c in ebs.put_snapshot_block.call_args_list), key=lambda c:c['BlockIndex'])
        self.assertEqual([c['BlockIndex'] for c in calls], [1,9])
        for call, (_, data) in zip(calls, blocks):
            self.assertEqual(call['BlockData'], data)
            self.assertEqual(call['Checksum'], base64.b64encode(hashlib.sha256(data).digest()).decode())
        ebs.complete_snapshot.assert_called_once_with(SnapshotId='snap-new', ChangedBlocksCount=2)
        self.assertNotIn('ParentSnapshotId', ebs.start_snapshot.call_args.kwargs)

    def test_truncated_stream_never_completes_a_snapshot(self):
        process = Mock(stdout=io.BytesIO(struct.pack('!QI', 1, 200)+b'short'))
        ebs = Mock(); ebs.start_snapshot.return_value = {'SnapshotId':'snap-new'}
        with tempfile.TemporaryDirectory() as directory, patch.object(module.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'ended prematurely'):
                module.create_snapshot(ebs, ['ssh','worker'], 'vol-123', 1, 'test', [], Path(directory)/'state.json')
        ebs.complete_snapshot.assert_not_called()
        process.terminate.assert_called_once()

    def test_existing_state_prevents_duplicate_snapshot_allocation(self):
        ebs = Mock()
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)/'state.json'; state.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'state already exists'):
                module.create_snapshot(ebs, ['ssh','worker'], 'vol-123', 1, 'test', [], state)
        ebs.start_snapshot.assert_not_called()
