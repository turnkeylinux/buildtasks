#!/usr/bin/env python
# Copyright (c) 2013 Alon Swartz <alon@turnkeylinux.org>
"""
Create S3 AMI from rootfs and upload

Arguments:

    rootfs              Path to rootfs

Options:

    --region=           Target region (default: current region)
    --bucket=           Target bucket (default: turnkeylinux-$REGION)
    --size=             Size of snapshot (default: 10)
    --fs=               File system of snapshot (default: ext4)

Environment:

    AWS_X509_DIR        Path to directory containing cert.pem and pk.pem
                        Default: /turnkey/buildtasks/config/ec2
    EC2_AMITOOL_HOME    Path to ec2-ami-tools directory
                        Default: /usr/local/src/ec2-ami-tools

"""
import os
import sys
import getopt

import conf
import utils

import executil

log = utils.get_logger('s3-bundle')

AWS_X509_DIR = "/turnkey/buildtasks/config/ec2"
EC2_AMITOOL_HOME = "/usr/local/src/ec2-ami-tools"

class Error(Exception):
    pass

def fatal(e):
    print >> sys.stderr, "error: " + str(e)
    sys.exit(1)

def usage(e=None):
    if e:
        print >> sys.stderr, "error: " + str(e)

    print >> sys.stderr, "Syntax: %s [ -options ] rootfs" % (sys.argv[0])
    print >> sys.stderr, __doc__.strip()

    sys.exit(1)

def _get_pem_paths():
    path = os.getenv("AWS_X509_DIR", AWS_X509_DIR)
    cert = os.path.join(path, "cert.pem")
    pk = os.path.join(path, "pk.pem")

    for pem in (cert, pk):
        if not os.path.exists(pem):
            raise Error("does not exist: %s" % pem)

    return {'cert': cert, 'pk': pk}

def _get_amitools_path():
    path = os.getenv("EC2_AMITOOL_HOME", EC2_AMITOOL_HOME)
    if not os.path.exists(path):
        raise Error("does not exist: %s" % path)

    return path

def _amitools_cmd(command, opts):
    amitools_path = _get_amitools_path()
    os.environ["EC2_AMITOOL_HOME"] = amitools_path

    log.debug("amitools_cmd - %s %s", command, opts)
    cmd = os.path.join(amitools_path, 'bin', command)
    executil.system(cmd, *opts)

def _bundle_upload(region, ami_name, bucket):
    manifest = ami_name + ".manifest.xml"

    locations = {"us-east-1": "US", "eu-west-1": "EU"}
    location = locations[region] if locations.has_key(region) else region

    opts = []
    opts.extend(["--batch", "--retry"])
    opts.extend(["--access-key", conf.SMP_ACCESSKEY])
    opts.extend(["--secret-key", conf.SMP_SECRETKEY])
    opts.extend(["--location", location])
    opts.extend(["--bucket", bucket])
    opts.extend(["--manifest", ami_name + ".manifest.xml"])

    _amitools_cmd('ec2-upload-bundle', opts)
    log.info("upload complete - %s/%s.manifest.xml", bucket, ami_name)

def _bundle_image(region, path, ami_name, arch, pems):
    opts = []
    opts.extend(["--cert", pems['cert']])
    opts.extend(["--privatekey", pems['pk']])
    opts.extend(["--user", conf.SMP_USERID])
    opts.extend(["--destination", os.getcwd()])
    opts.extend(["--arch", "x86_64" if arch == "amd64" else arch])
    opts.extend(["--kernel", conf.KERNELS[region][arch]])
    opts.extend(["--prefix", ami_name])
    opts.extend(["--image", path])

    _amitools_cmd('ec2-bundle-image', opts)
    log.info("bundle complete - %s", ami_name)

def bundle(rootfs, region, bucket=None, size=10, filesystem='ext4'):
    _get_amitools_path()
    pems = _get_pem_paths()

    log.info('creating loopback, formatting and mounting')
    image_path = rootfs + '.img'
    image_mount = rootfs + '.img.mount'
    utils.mkdir(image_mount)
    executil.system('dd if=/dev/null of=%s bs=1 seek=%dG' % (image_path, size))
    executil.system('mkfs.' + filesystem, '-F', '-j', image_path)
    executil.system('mount -o loop', image_path, image_mount)

    log.info('syncing rootfs to loopback')
    utils.rsync(rootfs, image_mount)

    log.debug('umounting loopback')
    executil.system('umount', '-d', image_mount)
    os.removedirs(image_mount)

    log.debug('getting unique ami name')
    app = utils.get_turnkey_version(rootfs)
    ami_name = utils.get_uniquename(region, app + '.s3')
    log.info('target ami_name - %s ', ami_name)

    log.info('bundling loopback into ami')
    arch = utils.parse_imagename(ami_name)['architecture']
    _bundle_image(region, image_path, ami_name, arch, pems)
    os.remove(image_path)

    log.info('uploading bundled ami')
    bucket = bucket if bucket else "turnkeylinux-" + region
    _bundle_upload(region, ami_name, bucket)

    log.info("complete - %s %s", bucket, ami_name)
    return bucket, ami_name

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
            ["help", "region=", "bucket=", "size=", "fs="])
    except getopt.GetoptError, e:
        usage(e)

    fs = 'ext4'
    size = 10
    region = None
    bucket = None
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--size":
            size = int(val)

        if opt == "--fs":
            fs = val

        if opt == "--region":
            region = val

        if opt == "--bucket":
            bucket = val

    if len(args) != 1:
        usage("incorrect number of arguments")

    rootfs = args[0]
    if not os.path.exists(rootfs):
        fatal("rootfs path does not exist: %s" % rootfs)

    region = region if region else utils.get_region()
    bucket, ami_name = bundle(rootfs, region, bucket, size, fs)
    print "%s - %s" (bucket, ami_name)

if __name__ == "__main__":
    main()

