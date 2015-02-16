#!/usr/bin/python
# Copyright (c) 2011-2015 TurnKey GNU/Linux - http://www.turnkeylinux.org
# 
# This file is part of buildtasks.
# 
# Buildtasks is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.

"""Generate config/docker.ports from hub stable appliances"""

import sys

sys.path.insert(0, '/turnkey/public/hub/apps/appliance')
from appliances import appliances

def main():
    for a in appliances:
        ports = []
        for p in a.fw.tcp:
            if ":" in p:
                start, end = p.split(":")
                for p in range(int(start), int(end) + 1):
                    ports.append(str(p))
            else:
                ports.append(p)

        for p in a.fw.udp:
            ports.append(p + '/udp')

        print "%s: %s" % (a.name, ' '.join(ports))

if __name__ == "__main__":
    main()

