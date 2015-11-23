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
Create snapshot from rootfs

Arguments:

    rootfs          Path to rootfs

Options:

    --size=         Size of snapshot (default: 10)
    --fs=           File system of snapshot (default: ext4)

"""
import os
import sys
import getopt
import time

import utils

import executil

from boto.exception import EC2ResponseError

log = utils.get_logger('ebs-bundle')

def fatal(e):
    print >> sys.stderr, "error: " + str(e)
    sys.exit(1)

def usage(e=None):
    if e:
        print >> sys.stderr, "error: " + str(e)

    print >> sys.stderr, "Syntax: %s [ -options ] rootfs" % (sys.argv[0])
    print >> sys.stderr, __doc__.strip()

    sys.exit(1)

class Error(Exception):
    pass

class Snapshot:
    def __init__(self, region=None):
        self.region = region if region else utils.get_region()
        self.conn = utils.connect(self.region)
        self.snap = None

    def _wait(self, status):
        while self.snap.status != status:
            time.sleep(1)
            self.snap.update()

        time.sleep(3)

    def create(self, volume_id, name):
        log.debug('creating snapshot - %s %s', volume_id, name)

        self.snap = self.conn.create_snapshot(volume_id, name)
        self._wait("completed")

        log.debug('created snapshot - %s', self.snap.id)

class Volume:
    def __init__(self, region=None):
        self.region = region if region else utils.get_region()
        self.conn = utils.connect(self.region)
        self.vol = None
        self.device = None

    def _wait(self, status):
        while self.vol.status != status:
            time.sleep(1)
            self.vol.update()

        time.sleep(3)

    def create(self, size, zone=None):
        zone = zone if zone else utils.get_zone()
        log.debug('creating volume - %d %s', size, zone)

        self.vol = self.conn.create_volume(size, zone)
        self._wait("available")
        log.debug('created volume - %s', self.vol.id)

    def delete(self, max_attempts=5):
        if self.vol:
            attempt = 0
            while True:
                attempt += 1
                log.debug('deleting volume %s (attempt %d)', self.vol.id, attempt)
                self._wait("available")
                try:
                    self.vol.delete()
                    break
                except EC2ResponseError, e:
                    error_code = e.errors[0][0]
                    log.debug('delete failed %s - %s)', self.vol.id, error_code)
                    if not error_code == "Client.VolumeInUse":
                        raise

                    if max_attempts == attempt:
                        log.debug('all delete attempts failed - %s)', self.vol.id)
                        raise

            self.vol = None

    def attach(self, instance_id, device):
        self.device = device
        if self.vol:
            log.debug('attaching volume - %s (%s)',
                      self.device.real_path, self.device.amazon_path)

            self.vol.attach(instance_id, self.device.amazon_path)
            while not self.device.exists():
                time.sleep(1)

            log.debug('attached volume')

    def detach(self):
        if self.device:
            if self.device.is_mounted():
                log.debug('umounting device before detaching volume')
                self.device.umount()

            if self.vol:
                log.debug('detaching volume')

                self._wait("available")
                self.vol.detach()
                self.device = None

    def __del__(self):
        self.detach()
        self.delete(max_attempts=1)

class Device:
    def __init__(self):
        self.real_path = self._get_freedevice()
        if not self.real_path:
            raise Error("no free devices available...")

        self.amazon_path = '/dev/sd' + self.real_path[-1]
        self.root_path = None

    @staticmethod
    def _get_freedevice():
        for s in 'fghijk':
            real_device = '/dev/xvd' + s
            if not os.path.exists(real_device):
                return real_device

        return None

    def is_mounted(self):
        return utils.is_mounted(self.real_path)

    def exists(self):
        return os.path.exists(self.real_path)

    def mount(self, mount_path):
        log.debug('mounting - %s %s', self.real_path, mount_path)
        utils.mkdir(mount_path)
        executil.system('mount', self.real_path, mount_path)

    def umount(self):
        log.debug('umounting - %s', self.real_path)
        executil.system('umount', '-f', self.real_path)

    def mkfs(self, fs):
        log.debug('mkfs - %s', self.real_path)
        executil.system('mkfs.' + fs, '-F', '-j', self.real_path)

    def mkpart(self):
        executil.system('parted', self.real_path, '--script', 'unit mib mklabel gpt mkpart primary 1 3 name 1 grub set 1 bios_grub on mkpart primary ext4 3 -1 name 2 rootfs quit')
        executil.system('partprobe', self.real_path)
        self.root_path = self.real_path
        self.real_path = self.real_path + '2'

    def __del__(self):
        if self.is_mounted():
            self.umount()

def bundle(rootfs, size=10, filesystem='ext4'):
    log.debug('getting unique snapshot name')
    turnkey_version = utils.get_turnkey_version(rootfs)
    snapshot_name = '_'.join([turnkey_version, str(int(time.time()))])
    log.info('target snapshot - %s ', snapshot_name)

    log.info('creating volume, attaching, formatting and mounting')
    volume = Volume()
    volume.create(size)

    device = Device()
    volume.attach(utils.get_instanceid(), device)

    log.info('creating partitions')
    device.mkpart()
    device.mkfs(filesystem)
    mount_path = rootfs + '.mount'
    device.mount(mount_path)

    log.info('syncing rootfs to partition')
    utils.rsync(rootfs, mount_path)

    log.info('installing GRUB on volume')
    submounts = ['/sys', '/proc', '/dev']
    for i in submounts:
        executil.system('mount', '--bind', i, mount_path + i)

    executil.system('chroot', mount_path, 'grub-install', device.root_path)
    executil.system('chroot', mount_path, 'update-grub')
    executil.system('chroot', mount_path, 'update-initramfs', '-u')

    for i in submounts:
        executil.system('umount', mount_path + i)

    device.umount()
    volume.detach()
    os.removedirs(mount_path)

    log.info('creating snapshot from volume')
    snapshot = Snapshot()
    snapshot.create(volume.vol.id, snapshot_name)

    volume._wait("available")
    volume.delete()

    log.info("complete - %s %s", snapshot.snap.id, snapshot.snap.description)
    return snapshot.snap.id, snapshot.snap.description

def main():
    try:
        l_opts = ["help", "size=", "filesystem="]
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", l_opts)
    except getopt.GetoptError, e:
        usage(e)

    kwargs = {
        'filesystem': 'ext4',
        'size': 10,
    }
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--size":
            kwargs['size'] = int(val)

        if opt == "--filesystem":
            kwargs['filesystem'] = val

    if len(args) != 1:
        usage("incorrect number of arguments")

    rootfs = args[0]
    if not os.path.exists(rootfs):
        fatal("rootfs path does not exist: %s" % rootfs)

    snapshot_id, snapshot_name = bundle(rootfs, **kwargs)

    print snapshot_id, snapshot_name

if __name__ == "__main__":
    main()

