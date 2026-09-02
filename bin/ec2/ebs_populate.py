#!/usr/bin/python3
"""Populate a pre-attached EBS device from a prepared root filesystem."""

import argparse
import os

from ebs_bundle import Device, populate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rootfs")
    parser.add_argument("device")
    args = parser.parse_args()
    if not os.path.isdir(args.rootfs):
        parser.error("rootfs path does not exist")
    if not os.path.exists(args.device):
        parser.error("device path does not exist")
    populate(args.rootfs, Device(args.device))


if __name__ == "__main__":
    main()
