#!/usr/bin/python3
# Author: Alon Swartz <alon@turnkeylinux.org>
# Copyright (c) 2011-2022 TurnKey GNU/Linux - http://www.turnkeylinux.org
#
# This file is part of buildtasks.
#
# Buildtasks is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.

"""
Create Amazon EC2 EBS-backed HVM AMI from rootfs

Arguments:

    rootfs          Path to rootfs

Options:
    --name=         Use as name basis (default: turnkey_version + ctime)
    --copy          Copy created AMI to all other regions
    --publish       Set AMI launch permission to public
    --marketplace   Share snapshot with AWS marketplace userid

Environment:

    AWS_ACCESS_KEY_ID       AWS Access Key ID (required)
    AWS_SECRET_ACCESS_KEY   AWS Secret Access Key (required)
    AWS_SESSION_TOKEN       AWS Session Token

"""
import os
import sys
import time
import getopt

import utils

from ebs_bundle import bundle
from ebs_register import register
from ebs_publish import share_public
from ebs_share import share_marketplace
from ec2_copy import copy_image

log = utils.get_logger('ebs')


def fatal(e):
    print("error: " + str(e), file=sys.stderr)
    sys.exit(1)


def usage(e=None):
    if e:
        print("error: " + str(e), file=sys.stderr)

    print("Syntax: %s [ -options ] rootfs" % (sys.argv[0]), file=sys.stderr)
    print(__doc__.strip(), file=sys.stderr)

    sys.exit(1)


def main():
    try:
        l_opts = ["help", "copy", "publish", "marketplace", "pvmregister", "name="]
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", l_opts)
    except getopt.GetoptError as e:
        usage(e)

    name = None
    copy = False
    publish = False
    marketplace = False
    pvmregister = False
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--name":
            name = val

        if opt == "--copy":
            copy = True

        if opt == "--publish":
            publish = True

        if opt == "--marketplace":
            marketplace = True

        if opt == "--pvmregister":
            pvmregister = True

    if len(args) != 1:
        usage("incorrect number of arguments")

    rootfs = args[0]
    if not os.path.exists(rootfs):
        fatal("rootfs path does not exist: %s" % rootfs)

    if not name:
        turnkey_version = utils.get_turnkey_version(rootfs)
        name = '_'.join([turnkey_version, str(int(time.time()))])

    arch = utils.get_arch()
    region = utils.get_region()
    snapshot_id, snapshot_name = bundle(rootfs, name)
    log.important(' '.join([snapshot_id, arch, region]))

    if marketplace:
        share_marketplace(snapshot_id, region)

    ami_id, ami_name = register(snapshot_id, region, arch)

    log.info(ami_name)
    log.important(' '.join([ami_id, arch, region]))

    if pvmregister:
        ami_id, ami_name = register(snapshot_id, region, arch, pvm=True)

        log.info(ami_name + ' (PVM)')
        log.important(' '.join([ami_id, arch, region, '(PVM)']))

    if publish:
        share_public(ami_id, region)

    if copy:
        regions = utils.get_all_regions()
        regions.remove(region)
        images = copy_image(ami_id, ami_name, region, regions)

        for image in images:
            log.important(' '.join([image.id, arch, image.region]))


if __name__ == "__main__":
    main()
