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
Set AMI launch permission to all

Arguments:

    ami_id          Amazon Image ID

Options:

    --region=       Region (default: current region)

"""
import sys
import getopt

import utils

log = utils.get_logger('ebs-publish')


def usage(e=None):
    if e:
        print("error: " + str(e), file=sys.stderr)

    print("Syntax: %s [ -options ] ami_id" % (sys.argv[0]), file=sys.stderr)
    print(__doc__.strip(), file=sys.stderr)

    sys.exit(1)


def share_public(ami_id, region):
    conn = utils.connect(region)

    log.debug(f'setting image to public - {ami_id}')
    conn.modify_image_attribute(
        ami_id,
        attribute='launchPermission',
        operation='add',
        groups=['all'])

    log.info(f'set image to public - {ami_id}')


def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", ["help", "region="])
    except getopt.GetoptError as e:
        usage(e)

    region = None
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--region":
            region = val

    if len(args) != 1:
        usage("incorrect number of arguments")

    ami_id = args[0]
    region = region if region else utils.get_region()

    share_public(ami_id, region)


if __name__ == "__main__":
    main()
