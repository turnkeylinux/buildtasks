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
        self.snap = self.conn.create_snapshot(volume_id, name)
        self._wait("completed")

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
        self.vol = self.conn.create_volume(size, zone)
        self._wait("available")

    def delete(self):
        if self.vol:
            self._wait("available")
            self.vol.delete()
            self.vol = None

    def attach(self, instance_id, device):
        self.device = device
        if self.vol:
            self.vol.attach(instance_id, self.device.amazon_path)
            while not self.device.exists():
                time.sleep(1)

    def detach(self):
        if self.device:
            if self.device.is_mounted():
                self.device.umount()

            if self.vol:
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
        utils.mkdir(mount_path)
        executil.system('mount', self.real_path, mount_path)

    def umount(self):
        executil.system('umount', '-f', self.real_path)

    def mkfs(self, fs):
        executil.system('mkfs.' + fs, '-F', '-j', self.real_path)

    def __del__(self):
        if self.is_mounted():
            self.umount()

def bundle(rootfs, size=10, filesystem='ext4'):
    app = utils.get_turnkey_version(rootfs)
    snapshot_name = utils.get_uniquename(utils.get_region(), app + '.ebs')

    volume = Volume()
    volume.create(size)

    device = Device()
    volume.attach(utils.get_instanceid(), device)
    device.mkfs(filesystem)
    mount_path = rootfs + '.mount'
    device.mount(mount_path)

    utils.rsync(rootfs, mount_path)

    device.umount()
    volume.detach()
    os.removedirs(mount_path)

    snapshot = Snapshot()
    snapshot.create(volume.vol.id, snapshot_name)
    volume.delete()

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

