#!/usr/bin/env python
# Copyright (c) 2013 Alon Swartz <alon@turnkeylinux.org>
"""
Copy AMI to destination region(s)

Arguments:

    ami_id              Amazon Image ID
    ami_name            Amazon Image Name
    ami_region          Amazon Image Region
    region...regionN    Destination region(s) to copy to (also accepts: all)

"""
import sys
import getopt

import utils

log = utils.get_logger('ebs-copy')

def fatal(e):
    print >> sys.stderr, "error: " + str(e)
    sys.exit(1)

def usage(e=None):
    if e:
        print >> sys.stderr, "error: " + str(e)

    args = "ami_id ami_name ami_region region...regionN"
    print >> sys.stderr, "Syntax: %s %s" % (sys.argv[0], args)
    print >> sys.stderr, __doc__.strip()

    sys.exit(1)

class Image:
    def __init__(self, ami_id, region):
        self.id = ami_id
        self.region = region

    def get(self):
        conn = utils.connect(self.region)
        return conn.get_all_images(image_ids=[self.id])[0]

def copy_image(ami_id, ami_name, ami_region, regions=[]):
    images = []
    for region in regions:
        if region == ami_region:
            continue

        log.debug('copying %s (%s) to %s', ami_id, ami_region, region)

        conn = utils.connect(region)
        ret = conn.copy_image(ami_region, ami_id, ami_name)
        image = Image(ret.image_id, region)
        images.append(image)

        log.info('pending %s (%s) to %s (%s)', ami_id, ami_region, image.id, region)

    return images

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", ["help"])
    except getopt.GetoptError, e:
        usage(e)

    publish = False
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

    if len(args) < 4:
        usage("incorrect number of arguments")

    ami_id, ami_name, ami_region = args[:3]
    regions = args[3:]

    if 'all' in regions:
        regions = utils.get_regions()

    images = copy_image(ami_id, ami_name, ami_region, regions)
    for image in images:
        print "%s - %s" % (image.id, image.region)


if __name__ == "__main__":
    main()

