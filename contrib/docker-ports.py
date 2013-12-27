#!/usr/bin/python
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

