#!/usr/bin/env python
# Copyright (c) 2013 Alon Swartz <alon@turnkeylinux.org>
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

def usage(e=None):
    if e:
        print >> sys.stderr, "error: " + str(e)

    print >> sys.stderr, "Syntax: %s [ -options ] snapshot_id" % (sys.argv[0])
    print >> sys.stderr, __doc__.strip()

    sys.exit(1)

def share_marketplace(snapshot_id, region):
    conn = utils.connect(region)
    snapshot = conn.get_all_snapshots(snapshot_ids=[snapshot_id])[0]
    snapshot.share(user_ids=['679593333241'])

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", ["help", "region="])
    except getopt.GetoptError, e:
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

