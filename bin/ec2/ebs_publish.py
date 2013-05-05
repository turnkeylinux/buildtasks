#!/usr/bin/env python
# Copyright (c) 2013 Alon Swartz <alon@turnkeylinux.org>
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
        print >> sys.stderr, "error: " + str(e)

    print >> sys.stderr, "Syntax: %s [ -options ] ami_id" % (sys.argv[0])
    print >> sys.stderr, __doc__.strip()

    sys.exit(1)

def share_public(ami_id, region):
    conn = utils.connect(region)

    log.debug('setting image to public - %s', ami_id)
    conn.modify_image_attribute(
        ami_id,
        attribute='launchPermission',
        operation='add',
        groups=['all'])

    log.info('set image to public - %s' % ami_id)

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

    ami_id = args[0]
    region = region if region else utils.get_region()

    share_public(ami_id, region)

if __name__ == "__main__":
    main()

