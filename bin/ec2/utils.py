# Author: Alon Swartz <alon@turnkeylinux.org>
# Copyright (c) 2011-2015 TurnKey GNU/Linux - http://www.turnkeylinux.org
# 
# This file is part of buildtasks.
# 
# Buildtasks is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.


import re
import os
import sys
import logging

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

def get_regions():
    return conf.KERNELS.keys()

def get_kernel(region, arch):
    return conf.KERNELS[region][arch]

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

def get_logger(name, level=None):
    logger = logging.getLogger(name)

    if not logger.handlers:
        stdout = logging.StreamHandler(sys.stdout)
        stdout.setFormatter(logging.Formatter(
            '%(levelname)s [%(name)s]: %(message)s'))
        logger.addHandler(stdout)

        level = level if level else conf.LOG_LEVEL
        logger.setLevel(getattr(logging, level))

    return logger

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

def parse_imagename(s):
    parsed = {}
    m = re.match("turnkey-(.*)-(\w[-+0-9a-z.]*)-(.*)-(.*).(ebs|s3.*)", s)
    if m:
        parsed['appname'] = m.groups()[0]
        parsed['version'] = m.groups()[1]
        parsed['distro'] = m.groups()[2]
        parsed['architecture'] = m.groups()[3]
        parsed['url'] = 'http://www.turnkeylinux.org/' + parsed['appname']

    return parsed

