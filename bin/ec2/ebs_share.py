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
Share snapshot with Amazon marketplace

Arguments:

    snapshot_id     Snapshot ID

Options:

    --region=       Region (default: current region)

"""
import sys
import getopt

import utils

log = utils.get_logger('ebs-share')


def usage(e=None):
    if e:
        print("error: " + str(e), file=sys.stderr)

    print("Syntax: %s [ -options ] snapshot_id" % (sys.argv[0]), file=sys.stderr)
    print(__doc__.strip(), file=sys.stderr)

    sys.exit(1)


def share_marketplace(snapshot_id, region):
    conn = utils.connect(region)

    log.debug(f'getting snapshot - {snapshot_id}')
    snapshot = conn.get_all_snapshots(snapshot_ids=[snapshot_id])[0]

    log.debug('sharing with marketplace')
    snapshot.share(user_ids=['096457495696'])

    log.info(f'shared with marketplace - {snapshot_id}')


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

    snapshot_id = args[0]
    region = region if region else utils.get_region()

    share_marketplace(snapshot_id, region)


if __name__ == "__main__":
    main()
