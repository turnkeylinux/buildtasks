#!/usr/bin/python3
# Author: Alon Swartz <alon@turnkeylinux.org>
# Copyright (c) 2011-2026 TurnKey GNU/Linux - https://www.turnkeylinux.org
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

from . import utils

log = utils.get_logger('ebs-register')


def fatal(e):
    print("error: " + str(e), file=sys.stderr)
    sys.exit(1)


def usage(e=None):
    if e:
        print("error: " + str(e), file=sys.stderr)

    print("Syntax: %s [ opts ] snapshot_id" % (sys.argv[0]), file=sys.stderr)
    print(__doc__.strip(), file=sys.stderr)

    sys.exit(1)


def register(snapshot_id, region, arch, size=None,
             name=None, desc=None):
    client3 = utils.connect_boto3(region)

    if None in (name, size):
        log.debug(f'getting snapshot - {snapshot_id}')

        snap_response = client3.describe_snapshots(SnapshotIds=[snapshot_id])
        snapshot = snap_response["Snapshots"][0]
        size = size if size else snapshot["VolumeSize"]
        name = name if name else snapshot.get(
            "Description",
            f"Snapshot {snapshot_id}",
        )

    virt = 'hvm'
    device_base = '/dev/xvd'
    ec2_arch = "x86_64" if arch == "amd64" else arch

    log.debug("creating block_device_mappings")

    rootfs_device_name = device_base + 'a'
    block_device_mappings = [
        {
            "DeviceName": rootfs_device_name,
            "Ebs": {
                "SnapshotId": snapshot_id,
                "VolumeSize": size,
                "DeleteOnTermination": True
            },
        },
        {
            "DeviceName": device_base + "b",
            "VirtualName": "ephemeral0"
        },
    ]
    log.debug(f'registering image - {name}')
    client3 = utils.connect_boto3(region)

    response = client3.register_image(
        Name=name,
        Architecture=ec2_arch,
        RootDeviceName=rootfs_device_name,
        BlockDeviceMappings=block_device_mappings,
        VirtualizationType=virt,
        EnaSupport=True,
    )

    ami_id = response['ImageId']

    log.info(f'registered image - {ami_id} {name} {region}')
    return ami_id, name


def main():
    try:
        l_opts = ["help", "region=", "size=", "name=", "arch=", "desc="]
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", l_opts)
    except getopt.GetoptError as e:
        usage(e)

    kwargs = {
        'size': None,
        'name': None,
        'desc': None,
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

    if len(args) != 1:
        usage("incorrect number of arguments")

    snapshot_id = args[0]
    arch = arch if arch else utils.get_arch()
    region = region if region else utils.get_region()

    ami_id, ami_name = register(snapshot_id, region, arch, **kwargs)
    print(ami_id, ami_name)


if __name__ == "__main__":
    main()
