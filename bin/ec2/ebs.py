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
Create Amazon EC2 EBS-backed AMI(s) from rootfs

Arguments:

    rootfs          Path to rootfs

Options:
    --virt=         Virtualization type: hvm, pvm (default: hvm and pvm)
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
import getopt

import utils

from ebs_bundle import bundle
from ebs_register import register
from ebs_publish import share_public
from ebs_share import share_marketplace
from ec2_copy import copy_image

log = utils.get_logger('ebs')

def fatal(e):
    print >> sys.stderr, "error: " + str(e)
    sys.exit(1)

def usage(e=None):
    if e:
        print >> sys.stderr, "error: " + str(e)

    print >> sys.stderr, "Syntax: %s [ -options ] rootfs" % (sys.argv[0])
    print >> sys.stderr, __doc__.strip()

    sys.exit(1)

def main():
    try:
        l_opts = ["help", "copy", "publish", "marketplace", "virt="]
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", l_opts)
    except getopt.GetoptError, e:
        usage(e)


    virts = []
    copy = False
    publish = False
    marketplace = False
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--virt":
            virts.append(val)

        if opt == "--copy":
            copy = True

        if opt == "--publish":
            publish = True

        if opt == "--marketplace":
            marketplace = True

    if len(args) != 1:
        usage("incorrect number of arguments")

    rootfs = args[0]
    if not os.path.exists(rootfs):
        fatal("rootfs path does not exist: %s" % rootfs)

    if not virts:
        virts = ['hvm', 'pvm']

    for virt in virts:
        if not virt in ('hvm', 'pvm'):
            fatal("virtualization type not supported: %s" % virt)

    region = utils.get_region()
    snapshot_id, snapshot_name = bundle(rootfs)

    if marketplace:
        share_marketplace(snapshot_id, region)

    for virt in virts:
        ami_id, ami_name = register(snapshot_id, region, virt)
        log.info(ami_name)
        log.info("  %s - %s" % (ami_id, region))

        if publish:
            share_public(ami_id, region)

        if copy:
            regions = utils.get_all_regions()
            regions.remove(region)
            images = copy_image(ami_id, ami_name, region, regions)

            for image in images:
                log.info("  %s - %s" % (image.id, image.region))


if __name__ == "__main__":
    main()

