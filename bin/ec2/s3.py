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
Create Amazon EC2 S3-backed AMI from rootfs

Arguments:

    rootfs          Path to rootfs

Options:

    --region=       Target region (default: current region)

    --copy          Copy created AMI to all other regions
    --publish       Make AMI's public

"""
import os
import sys
import getopt

import utils

from s3_bundle import bundle
from s3_register import register
from s3_publish import share_public
from ec2_copy import copy_image

log = utils.get_logger('s3')

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
            ["help", "copy", "publish", "region="])
    except getopt.GetoptError, e:
        usage(e)

    copy = False
    publish = False
    region = None
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--region":
            region = val

        if opt == "--copy":
            copy = True

        if opt == "--publish":
            publish = True

    if len(args) != 1:
        usage("incorrect number of arguments")

    rootfs = args[0]
    if not os.path.exists(rootfs):
        fatal("rootfs path does not exist: %s" % rootfs)

    region = region if region else utils.get_region()

    bucket, ami_name = bundle(rootfs, region)
    ami_id = register(ami_name, region)

    if publish:
        share_public(ami_id, region)

    images = []
    if copy:
        images = copy_image(ami_id, ami_name, region, utils.get_regions())

    print ami_name
    print "  %s - %s" % (ami_id, region)
    for image in images:
        print "  %s - %s" % (image.id, image.region)
    print


if __name__ == "__main__":
    main()

