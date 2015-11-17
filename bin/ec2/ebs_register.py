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
    --size=         Image rootfs size (default: snapshot size)
    --name=         Image name (default: snapshot name, ie. $turnkey_version.ebs)
    --desc=         Image website link (default: enumerated from name)
    --arch=         Image architecture (default: enumerated from name)
    --virt=         Image virtualization type (default: hvm)

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

def register(snapshot_id, region, size=None, arch=None, name=None, desc=None, virt=None):
    conn = utils.connect(region)

    log.debug('getting snapshot - %s', snapshot_id)
    snapshot = conn.get_all_snapshots(snapshot_ids=[snapshot_id])[0]

    size = size if size else snapshot.volume_size
    name = name if name else snapshot.description
    desc = desc if desc else utils.parse_imagename(name)['url']
    arch = arch if arch else utils.parse_imagename(name)['architecture']
    virt = virt if virt else 'hvm'

    arch_ec2 = "x86_64" if arch == "amd64" else arch

    kernel_id = None
    if virt == 'paravirtual':
        kernel_id = utils.get_kernel(region, arch)

    log.debug('creating block_device_map')
    rootfs = BlockDeviceType()
    rootfs.delete_on_termination = True
    rootfs.size = size
    rootfs.snapshot_id = snapshot_id

    ephemeral = BlockDeviceType()
    ephemeral.ephemeral_name = 'ephemeral0'

    block_device_map = BlockDeviceMapping()

    rootdev = ephdev = None

    if virt == 'hvm':
        rootdev = '/dev/xvda'
        ephdev = '/dev/xvdb'
    else:
        rootdev = '/dev/sda1'
        ephdev = '/dev/sda2'

    block_device_map[rootdev] = rootfs
    block_device_map[ephdev] = ephemeral

    log.debug('registering image - %s', name)
    ami_id = conn.register_image(
        name=name,
        description=desc,
        architecture=arch_ec2,
        kernel_id=kernel_id,
        root_device_name=rootdev,
        block_device_map=block_device_map,
        virtualization_type=virt)

    log.info('registered image - %s %s %s', ami_id, name, region)
    return ami_id

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
            ["help", "region=", "size=", "name=", "desc=", "arch=", "virt="])
    except getopt.GetoptError, e:
        usage(e)

    region = size = name = desc = arch = virt = None
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

        if opt == "--virt":
            virt = val

    if len(args) != 1:
        usage("incorrect number of arguments")

    snapshot_id = args[0]
    region = region if region else utils.get_region()

    ami_id = register(snapshot_id, region, size, name, desc, arch, virt)
    print ami_id

if __name__ == "__main__":
    main()

