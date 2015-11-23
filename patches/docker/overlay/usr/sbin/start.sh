#!/bin/bash

# not recommended, useful for testing though...
if [ -n "$SEC_UPDATES" ]; then
    PRESEED=/usr/lib/inithooks/firstboot.d/29preseed
    sed -i "s|SEC_UPDATES=.*|SEC_UPDATES=$SEC_UPDATES|" $PRESEED
fi

run-parts -a start /etc/rc2.d
trap "run-parts -a stop /etc/rc2.d" INT TERM EXIT

turnkey-sysinfo

if [ -x /root/.profile.d/turnkey-init-fence ]; then
cat<<EOF

WARNING: The container requires initialization (performed on first login).
This can be performed from the host as follows:

    CID=\$(docker ps -l -q)
    CIP=\$(docker inspect -format='{{.NetworkSettings.IPAddress}}' \$CID)
    docker logs \$CID | grep "Random initial root password"
    ssh root@\$CIP
EOF
fi

cat<<EOF

WARNING: Exiting this shell will stop the container.
For regular console usage, SSH is recommended.
EOF

/bin/su


