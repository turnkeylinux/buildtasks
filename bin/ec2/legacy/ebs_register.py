#!/usr/bin/env python
# Author: Alon Swartz <alon@turnkeylinux.org>
# Copyright (c) 2011-2015 TurnKey GNU/Linux - http://www.turnkeylinux.org
#
# This file is part of buildtasks.
#
# Buildtasks is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.

"""
Register AMI from snapshot

Arguments:

    snapshot_id     Snapshot ID

Options:

    --region=       Snapshot region (default: current region)
    --size=         Image rootfs size (default: snapshot_size)
    --name=         Image name (default: snapshot_name)
    --arch=         Image architecture (default: system arch)
    --desc=         Image description (default: none)

"""
import sys
import getopt

import utils

from boto.ec2.blockdevicemapping import BlockDeviceType, BlockDeviceMapping
import boto3

log = utils.get_logger('ebs-register')

class Error(Exception):
    pass

def fatal(e):
    print >> sys.stderr, "error: " + str(e)
    sys.exit(1)

def usage(e=None):
    if e:
        print >> sys.stderr, "error: " + str(e)

    print >> sys.stderr, "Syntax: %s [ opts ] snapshot_id" % (sys.argv[0])
    print >> sys.stderr, __doc__.strip()

    sys.exit(1)

def register(snapshot_id, region, arch, size=None, name=None, desc=None, pvm=False):
    conn = utils.connect(region)

    if None in (name, size):
        log.debug('getting snapshot - %s', snapshot_id)
        snapshot = conn.get_all_snapshots(snapshot_ids=[snapshot_id])[0]
        size = size if size else snapshot.volume_size
        name = name if name else snapshot.description

    virt = 'hvm'
    kernel_id = None
    device_base = '/dev/xvd'
    ec2_arch = "x86_64" if arch == "amd64" else arch

    if pvm:
        kernel_id = utils.get_kernel(region, arch)
        virt = 'paravirtual'
        device_base = '/dev/sd'
        name += '-pvm'

    log.debug('creating block_device_map')
    block_device_map = BlockDeviceMapping()

    rootfs = BlockDeviceType()
    rootfs.delete_on_termination = True
    rootfs.size = size
    rootfs.snapshot_id = snapshot_id
    rootfs_device_name = device_base + 'a'
    block_device_map[rootfs_device_name] = rootfs

    ephemeral = BlockDeviceType()
    ephemeral.ephemeral_name = 'ephemeral0'
    ephemeral_device_name = device_base + 'b'
    block_device_map[ephemeral_device_name] = ephemeral

    log.debug('registering image - %s', name)
    client3 = utils.connect_boto3(region)
    
    response = client3.register_image(
        Name=name,
        Architecture=ec2_arch,
        RootDeviceName=rootfs_device_name,
        BlockDeviceMappings=[
            {
                'DeviceName': '/dev/xvda',
                'Ebs': {
                    'DeleteOnTermination': True,
                    'VolumeSize': size,
                    'SnapshotId': snapshot_id,
                },
            },
            {
                'DeviceName': '/dev/xvdb',
                'VirtualName': 'ephemeral0',
            }
        ],
        VirtualizationType=virt,
        EnaSupport=True)

    ami_id = response['ImageId']

    log.info('registered image - %s %s %s', ami_id, name, region)
    return ami_id, name

def main():
    try:
        l_opts = ["help", "pvm", "region=", "size=", "name=", "arch=", "desc="]
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", l_opts)
    except getopt.GetoptError, e:
        usage(e)

    kwargs = {
        'size': None,
        'name': None,
        'desc': None,
        'pvm' : False
    }
    arch = None
    region = None
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--arch":
            arch = val

        if opt == "--region":
            region = val

        if opt == "--size":
            kwargs['size'] = int(val)

        if opt == "--name":
            kwargs['name'] = val

        if opt == "--desc":
            kwargs['desc'] = val

        if opt == "--pvm":
            kwargs['pvm'] = True

    if len(args) != 1:
        usage("incorrect number of arguments")

    snapshot_id = args[0]
    arch = arch if arch else utils.get_arch()
    region = region if region else utils.get_region()

    ami_id, ami_name = register(snapshot_id, region, arch, **kwargs)
    print ami_id, ami_name

if __name__ == "__main__":
    main()

