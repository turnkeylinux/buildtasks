# Copyright (c) 2013 Alon Swartz <alon@turnkeylinux.org>

import os

import conf

import executil
import ec2metadata

from boto.ec2 import connect_to_region

def connect(region=None):
    region = region if region else get_region()
    return connect_to_region(
        region,
        aws_access_key_id=conf.SMP_ACCESSKEY,
        aws_secret_access_key=conf.SMP_SECRETKEY)

def get_turnkey_version(rootfs):
    return file(os.path.join(rootfs, "etc/turnkey_version")).read().strip()

def get_instanceid():
    return ec2metadata.get('instance-id')

def get_zone():
    return ec2metadata.get('availability-zone')

def get_region():
    return ec2metadata.get('availability-zone')[0:-1]

def get_uniquename(region, name):
    def get_imagenames(region):
        conn = connect(region)
        images = conn.get_all_images(owners=[conf.SMP_USERID])

        return set(map(lambda image: image.name, images))

    def get_snapshotnames(region):
        conn = connect(region)
        snapshots = conn.get_all_snapshots(owner=conf.SMP_USERID)

        return set(map(lambda snapshot: snapshot.description, snapshots))

    def inc_name(name):
        try:
            name, version = name.split('_')
            version = int(version) + 1
        except ValueError:
            version = 2

        return "_".join([name, str(version)])

    if name.endswith('.ebs'):
        names = get_snapshotnames(region)

    if name.endswith('.s3'):
        names = get_imagenames(region)

    while name in names:
        name = inc_name(name)

    return name

def is_mounted(path):
    mounts = file("/proc/mounts").read()
    if mounts.find(path) != -1:
        return True

    return False

def mkdir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def rsync(rootfs, dest):
    executil.system('rsync -a -t -r -S -I -H %s/ %s' % (rootfs, dest))

