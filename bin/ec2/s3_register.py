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
Register S3 AMI

Arguments:

    ami_name        Name of AMI

Options:

    --region=       AMI region (default: current region)
    --bucket=       AMI bucket (default: turnkeylinux-$REGION)
    --desc=         Image website link (default: enumerated from name)
    --arch=         Image architecture (default: enumerated from name)

"""
import os
import sys
import getopt

import utils

log = utils.get_logger('s3-register')

def usage(e=None):
    if e:
        print >> sys.stderr, "error: " + str(e)

    print >> sys.stderr, "Syntax: %s [ -options ] ami_name" % (sys.argv[0])
    print >> sys.stderr, __doc__.strip()

    sys.exit(1)

def register(ami_name, region, bucket=None, desc=None, arch=None):
    desc = desc if desc else utils.parse_imagename(ami_name)['url']
    bucket = bucket if bucket else "turnkeylinux-" + region
    image_location = os.path.join(bucket, ami_name + ".manifest.xml")

    log.debug('registering image - %s', image_location)
    conn = utils.connect(region)
    ami_id = conn.register_image(
        name=ami_name,
        description=desc,
        image_location=image_location)

    log.info('registered image - %s %s', ami_id, image_location)
    return ami_id

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
            ["help", "region=", "bucket=", "desc=", "arch="])
    except getopt.GetoptError, e:
        usage(e)

    region = bucket = desc = arch = None
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--region":
            region = val

        if opt == "--bucket":
            bucket = None

        if opt == "--desc":
            desc = val

        if opt == "--arch":
            arch = val

    if len(args) != 1:
        usage("incorrect number of arguments")

    ami_name = args[0]
    region = region if region else utils.get_region()

    ami_id = register(ami_name, region, bucket, arch, desc)
    print ami_id

if __name__ == "__main__":
    main()

