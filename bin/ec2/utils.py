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
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
        security_token=os.environ.get('AWS_SESSION_TOKEN', None))

def get_turnkey_version(rootfs):
    return file(os.path.join(rootfs, "etc/turnkey_version")).read().strip()

def get_instanceid():
    return ec2metadata.get('instance-id')

def get_zone():
    return ec2metadata.get('availability-zone')

def get_region():
    return ec2metadata.get('availability-zone')[0:-1]

def get_all_regions():
    return conf.KERNELS.keys()

def get_kernel(region, arch):
    return conf.KERNELS[region][arch]

def get_arch():
    return executil.getoutput('dpkg --print-architecture')

def get_logger(name, level=None):
    logger = logging.getLogger(name)

    if not logger.handlers:
        logging.addLevelName(45, 'IMPORTANT')
        setattr(logger, 'important',
                lambda *args, **kwargs: logger.log(45, *args, **kwargs))

        format = logging.Formatter('%(levelname)s [%(name)s]: %(message)s')

        stdout = logging.StreamHandler(sys.stdout)
        stdout.setFormatter(format)
        logger.addHandler(stdout)

        logfile = os.environ.get('LOGFILE_PATH', None)
        if logfile:
            filehandler = logging.FileHandler(logfile, mode='a')
            filehandler.setFormatter(format)
            logger.addHandler(filehandler)

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

