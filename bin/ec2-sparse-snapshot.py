#!/usr/bin/env python3
"""Create an EBS snapshot from nonzero blocks of an unmounted worker disk."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
from pathlib import Path
import shlex
import struct
import subprocess

import boto3
from botocore.config import Config

# The worker receives no AWS credentials. stdout is a framed binary stream.
WORKER = r'''
import os,stat,struct,subprocess,sys,zlib
volume=sys.argv[1];serial=volume.replace('-','')
rows=subprocess.check_output(['lsblk','-dnpo','NAME,SERIAL'],text=True).splitlines()
disks=[r.split()[0] for r in rows if len(r.split())==2 and r.split()[1]==serial]
assert len(disks)==1
path=disks[0];assert stat.S_ISBLK(os.stat(path).st_mode)
assert int(subprocess.check_output(['blockdev','--getsize64',path]))==int(sys.argv[2])*1024**3
assert not subprocess.check_output(['lsblk','-nr','-o','MOUNTPOINTS',path],text=True).strip()
blocksize=512*1024;zero=bytes(blocksize);out=sys.stdout.buffer
with open(path,'rb',buffering=0) as source:
 index=0
 while True:
  data=source.read(blocksize)
  if not data:break
  assert len(data)==blocksize
  if data!=zero:
   compressed=zlib.compress(data,1)
   out.write(struct.pack('!QI',index,len(compressed)));out.write(compressed)
  index+=1
out.write(struct.pack('!QI',2**64-1,0));out.flush()
print('DISK_BLOCKS_READ='+str(index),file=sys.stderr)
'''


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size-len(data))
        if not chunk:
            raise RuntimeError('Worker block stream ended prematurely')
        data.extend(chunk)
    return bytes(data)


def create_snapshot(ebs, ssh, volume, size, description, tags, state):
    import zlib
    state = Path(state)
    if state.exists():
        raise ValueError('Snapshot state already exists; inspect it before resuming')
    response = ebs.start_snapshot(VolumeSize=size, Description=description, Encrypted=False, Tags=tags)
    snapshot = response['SnapshotId']
    record = {'snapshot': snapshot, 'source_volume': volume, 'volume_size': size, 'status': 'STREAMING', 'blocks': 0}
    def save():
        state.write_text(json.dumps(record, indent=2)+'\n')
    save()
    command = 'sudo python3 -c ' + shlex.quote(WORKER) + ' ' + shlex.quote(volume) + ' ' + str(size)
    process = subprocess.Popen([*ssh, command], stdout=subprocess.PIPE, stderr=state.with_suffix('.worker.log').open('wb'))
    pending = set()
    count = 0
    previous = -1
    def upload(index, data):
        checksum = base64.b64encode(hashlib.sha256(data).digest()).decode()
        ebs.put_snapshot_block(SnapshotId=snapshot, BlockIndex=index, BlockData=data,
                               DataLength=len(data), Checksum=checksum, ChecksumAlgorithm='SHA256')
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            while True:
                index, length = struct.unpack('!QI', read_exact(process.stdout, 12))
                if index == 2**64-1:
                    if length:
                        raise ValueError('Invalid end marker')
                    break
                if not previous < index < size*2048 or not 0 < length <= 1024*1024:
                    raise ValueError('Invalid snapshot block frame')
                data = zlib.decompress(read_exact(process.stdout, length))
                if len(data) != 512*1024:
                    raise ValueError('Invalid snapshot block length')
                previous = index
                pending.add(pool.submit(upload, index, data))
                count += 1
                if len(pending) >= 16:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for job in done:
                        job.result()
                if count % 100 == 0:
                    record['blocks'] = count; save()
            for job in pending:
                job.result()
        if process.wait() != 0:
            raise RuntimeError('Worker failed; see worker log')
        ebs.complete_snapshot(SnapshotId=snapshot, ChangedBlocksCount=count)
        record.update(status='COMPLETION_REQUESTED', blocks=count, uploaded_bytes=count*512*1024)
        save()
        return record
    except BaseException as exc:
        process.terminate(); process.wait()
        record.update(status='FAILED', blocks=count, error=str(exc)); save()
        raise
    finally:
        process.stdout.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--access', required=True)
    p.add_argument('--volume', required=True)
    p.add_argument('--size', type=int, required=True)
    p.add_argument('--region', required=True)
    p.add_argument('--batch', required=True)
    p.add_argument('--app', required=True)
    p.add_argument('--state', required=True)
    a = p.parse_args()
    ssh = json.loads(Path(a.access).read_text())['ssh_argv']
    client = boto3.client('ebs', region_name=a.region, config=Config(retries={'max_attempts':5},max_pool_connections=16))
    result = create_snapshot(client, ssh, a.volume, a.size, a.batch+' '+a.app,
                             [{'Key':'RefreshBatch','Value':a.batch},{'Key':'TurnKeyApp','Value':a.app}],a.state)
    print(json.dumps(result,indent=2))

if __name__ == '__main__':
    main()
