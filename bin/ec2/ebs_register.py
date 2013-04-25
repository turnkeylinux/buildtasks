#!/usr/bin/env python
# Copyright (c) 2013 Alon Swartz <alon@turnkeylinux.org>
"""
Register AMI from snapshot

Arguments:

    snapshot_id     Snapshot ID

Options:

    --region=       Snapshot region (default: current region)
    --size=         Image rootfs size (default: snapshot size)
    --name=         Image name (default: snapshot name, ie. $turnkey_version.ebs)
    --desc=         Image website link (default: enumerated from name)
    --arch=         Image architecture (default: enumerated from name)

"""
import sys
import getopt

import utils

from boto.ec2.blockdevicemapping import BlockDeviceType, BlockDeviceMapping

log = utils.get_logger('ebs-register')

class Error(Exception):
    pass

def usage(e=None):
    if e:
        print >> sys.stderr, "error: " + str(e)

    print >> sys.stderr, "Syntax: %s [ -options ] snapshot_id" % (sys.argv[0])
    print >> sys.stderr, __doc__.strip()

    sys.exit(1)

def register(snapshot_id, region, size=None, arch=None, name=None, desc=None):
    conn = utils.connect(region)

    log.debug('getting snapshot - %s', snapshot_id)
    snapshot = conn.get_all_snapshots(snapshot_ids=[snapshot_id])[0]

    size = size if size else snapshot.volume_size
    name = name if name else snapshot.description
    desc = desc if desc else utils.parse_imagename(name)['url']
    arch = arch if arch else utils.parse_imagename(name)['architecture']
    kernel_id = utils.get_kernel(region, arch)

    log.debug('creating block_device_map')
    rootfs = BlockDeviceType()
    rootfs.delete_on_termination = True
    rootfs.size = size
    rootfs.snapshot_id = snapshot_id

    ephemeral = BlockDeviceType()
    ephemeral.ephemeral_name = 'ephemeral0'

    block_device_map = BlockDeviceMapping()
    block_device_map['/dev/sda1'] = rootfs
    block_device_map['/dev/sda2'] = ephemeral

    log.debug('registering image - %s', name)
    ami_id = conn.register_image(
        name=name,
        description=desc,
        architecture=arch,
        kernel_id=kernel_id,
        root_device_name="/dev/sda1",
        block_device_map=block_device_map)

    log.info('registered image - %s %s %s', ami_id, name, region)
    return ami_id

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
            ["help", "region=", "size=", "name=", "desc=", "arch="])
    except getopt.GetoptError, e:
        usage(e)

    region = size = name = desc = arch = None
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--region":
            region = val

        if opt == "--size":
            size = int(val)

        if opt == "--name":
            name = val

        if opt == "--desc":
            desc = val

        if opt == "--arch":
            arch = val

    if len(args) != 1:
        usage("incorrect number of arguments")

    snapshot_id = args[0]
    region = region if region else utils.get_region()

    ami_id = register(snapshot_id, region, size, name, desc, arch)
    print ami_id

if __name__ == "__main__":
    main()

