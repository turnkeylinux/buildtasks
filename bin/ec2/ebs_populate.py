#!/usr/bin/python3
"""Populate an explicitly selected, pre-attached disk; never call AWS APIs."""
import argparse
import os

from ebs_bundle import Device, populate, validate_local_device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-device", metavar="DEVICE",
                        help="validate a whole disk without populating it")
    parser.add_argument("rootfs", nargs="?")
    parser.add_argument("device", nargs="?")
    args = parser.parse_args()
    if args.check_device is not None:
        if args.rootfs is not None or args.device is not None:
            parser.error("--check-device does not accept rootfs/device positionals")
        validate_local_device(args.check_device)
        return
    if args.rootfs is None or args.device is None:
        parser.error("rootfs and device are required for population")
    if not os.path.isdir(args.rootfs):
        parser.error("rootfs path does not exist")
    device = validate_local_device(args.device)
    populate(args.rootfs, Device(device))


if __name__ == "__main__":
    main()
