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
    --name=         Image name (default: snapshot name*)
    --desc=         Image website link (default: enumerate from name*)
    --arch=         Image architecture (default: enumerate from name*)
    --virt=         Image virtualization type (default: enumerate from name*)

    *name: turnkey-appname-version-distro-arch.virt_timestamp

"""
import sys
import getopt

import utils

from boto.ec2.blockdevicemapping import BlockDeviceType, BlockDeviceMapping

log = utils.get_logger('ebs-register')

class Error(Exception):
    pass

def fatal(e):
    print >> sys.stderr, "error: " + str(e)
    sys.exit(1)

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
    arch = arch if arch else utils.parse_imagename(name)['arch']
    virt = virt if virt else utils.parse_imagename(name)['virt']

    arch_ec2 = "x86_64" if arch == "amd64" else arch

    log.debug('creating block_device_map')
    rootfs = BlockDeviceType()
    rootfs.delete_on_termination = True
    rootfs.size = size
    rootfs.snapshot_id = snapshot_id

    ephemeral = BlockDeviceType()
    ephemeral.ephemeral_name = 'ephemeral0'

    block_device_map = BlockDeviceMapping()

    if virt == 'pvm':
        kernel_id = None
        virt_ec2 = 'paravirtual'
        root_device_name = '/dev/sda1'
        block_device_map['/dev/sda1'] = rootfs
        block_device_map['/dev/sda2'] = ephemeral

    elif virt == 'hvm':
        kernel_id = utils.get_kernel(region, arch)
        virt_ec2 = 'hvm'
        root_device_name = '/dev/xvda'
        block_device_map['/dev/xvda'] = rootfs
        block_device_map['/dev/xvdb'] = ephemeral

    else:
        raise Error("virt not set or supported: %s" % virt)

    log.debug('registering image - %s', name)
    ami_id = conn.register_image(
        name=name,
        description=desc,
        architecture=arch_ec2,
        kernel_id=kernel_id,
        root_device_name=root_device_name,
        block_device_map=block_device_map,
        virtualization_type=virt_ec2)

    log.info('registered image - %s %s %s', ami_id, name, region)
    return ami_id

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
            ["help", "region=", "size=", "name=", "desc=", "arch=", "virt="])
    except getopt.GetoptError, e:
        usage(e)

    kwargs = {
        'size': None,
        'name': None,
        'desc': None,
        'arch': None,
        'virt': None,
    }
    region = None
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--region":
            region = val

        if opt == "--size":
            kwargs['size'] = int(val)

        if opt == "--name":
            kwargs['name'] = val

        if opt == "--desc":
            kwargs['desc'] = val

        if opt == "--arch":
            kwargs['arch'] = val

        if opt == "--virt":
            kwargs['virt'] = val

    if len(args) != 1:
        usage("incorrect number of arguments")

    snapshot_id = args[0]
    region = region if region else utils.get_region()
    ami_id = register(snapshot_id, region, **kwargs)

    print ami_id

if __name__ == "__main__":
    main()

