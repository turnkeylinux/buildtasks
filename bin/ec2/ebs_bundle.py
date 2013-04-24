#!/usr/bin/env python
# Copyright (c) 2013 Alon Swartz <alon@turnkeylinux.org>
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

    def delete(self):
        if self.vol:
            log.debug('deleting volume - %s', self.vol.id)

            self._wait("available")
            self.vol.delete()
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
        self.delete()

class Device:
    def __init__(self):
        self.real_path = self._get_freedevice()
        if not self.real_path:
            raise Error("no free devices available...")

        self.amazon_path = '/dev/sd' + self.real_path[-1]

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

    def __del__(self):
        if self.is_mounted():
            self.umount()

def bundle(rootfs, size=10, filesystem='ext4'):
    log.debug('getting unique snapshot name')
    app = utils.get_turnkey_version(rootfs)
    snapshot_name = utils.get_uniquename(utils.get_region(), app + '.ebs')
    log.info('target snapshot - %s ', snapshot_name)

    log.info('creating volume, attaching, formatting and mounting')
    volume = Volume()
    volume.create(size)

    device = Device()
    volume.attach(utils.get_instanceid(), device)

    device.mkfs(filesystem)
    mount_path = rootfs + '.mount'
    device.mount(mount_path)

    log.info('syncing rootfs to volume')
    utils.rsync(rootfs, mount_path)

    device.umount()
    volume.detach()
    os.removedirs(mount_path)

    log.info('creating snapshot from volume')
    snapshot = Snapshot()
    snapshot.create(volume.vol.id, snapshot_name)
    volume.delete()

    log.info("complete - %s %s", snapshot.snap.id, snapshot.snap.description)
    return snapshot.snap.id, snapshot.snap.description

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", ["help", "size=", "fs="])
    except getopt.GetoptError, e:
        usage(e)

    size = 10
    filesystem = 'ext4'
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()

        if opt == "--size":
            size = int(val)

        if opt == "--fs":
            fs = val

    if len(args) != 1:
        usage("incorrect number of arguments")

    rootfs = args[0]
    if not os.path.exists(rootfs):
        fatal("rootfs path does not exist: %s" % rootfs)

    snapshot_id, snapshot_name = bundle(rootfs, size=size, filesystem=fs)
    print "%s %s" % (snapshot_id, snapshot_name)

if __name__ == "__main__":
    main()

