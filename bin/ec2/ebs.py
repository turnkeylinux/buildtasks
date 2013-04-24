#!/usr/bin/env python
# Copyright (c) 2013 Alon Swartz <alon@turnkeylinux.org>
"""
Create Amazon EC2 EBS-backed AMI from rootfs

Arguments:

    rootfs          Path to rootfs

Options:

    --copy          Copy created AMI to all other regions
    --publish       Make AMI's public

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
            ["help", "copy", "publish"])
    except getopt.GetoptError, e:
        usage(e)


    copy = False
    publish = False
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

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

    snapshot_id, snapshot_name = bundle(rootfs)
    ami_id = register(snapshot_id, region)

    if publish:
        share_public(ami_id, region)
        share_marketplace(snapshot_id, region)

    images = []
    if copy:
        images = copy_image(ami_id, snapshot_name, region, utils.get_regions())

    print "="* 40
    print snapshot_name
    print "%s - %s" % (ami_id, region)
    for image in images:
        print "%s - %s" % (image.id, image.region)
    print "="* 40


if __name__ == "__main__":
    main()

