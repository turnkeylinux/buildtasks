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
Create Amazon EC2 EBS-backed AMI from rootfs

Arguments:

    rootfs          Path to rootfs

Options:

    --pv            Create PV-ready AMI instead of HVM
    --copy          Copy created AMI to all other regions
    --publish       Make AMIs public

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
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
            ["help", "pv", "copy", "publish"])
    except getopt.GetoptError, e:
        usage(e)


    virt = 'hvm'
    copy = False
    publish = False
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--pv":
            virt = 'paravirtual'

        if opt == "--copy":
            copy = True

        if opt == "--publish":
            publish = True

    if len(args) != 1:
        usage("incorrect number of arguments")

    rootfs = args[0]
    if not os.path.exists(rootfs):
        fatal("rootfs path does not exist: %s" % rootfs)

    region = utils.get_region()

    snapshot_id, snapshot_name = bundle(rootfs, virt)
    ami_id = register(snapshot_id, region, virt=virt)

    if publish:
        share_public(ami_id, region)
        share_marketplace(snapshot_id, region)

    images = []
    if copy:
        regions = utils.get_all_regions()
        regions.remove(region)
        images = copy_image(ami_id, snapshot_name, region, regions)

    print snapshot_name
    print "  %s - %s" % (ami_id, region)
    for image in images:
        print "  %s - %s" % (image.id, image.region)


if __name__ == "__main__":
    main()

