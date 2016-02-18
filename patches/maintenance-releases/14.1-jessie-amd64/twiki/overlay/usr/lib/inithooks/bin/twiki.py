#!/usr/bin/python
"""Set TWiki admin password and email

Option:
    --pass=     unless provided, will ask interactively
    --email=    unless provided, will ask interactively

"""

import sys
import getopt
import inithooks_cache

from executil import getoutput
from dialog_wrapper import Dialog

def usage(s=None):
    if s:
        print >> sys.stderr, "Error:", s
    print >> sys.stderr, "Syntax: %s [options]" % sys.argv[0]
    print >> sys.stderr, __doc__
    sys.exit(1)

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
                                       ['help', 'pass=', 'email='])
    except getopt.GetoptError, e:
        usage(e)

    password = ""
    email = ""
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()
        elif opt == '--pass':
            password = val
        elif opt == '--email':
            email = val

    if not password:
        d = Dialog('TurnKey Linux - First boot configuration')
        password = d.get_password(
            "TWiki Password",
            "Enter new password for the TWiki 'AdminUser' account.")

    if not email:
        if 'd' not in locals():
            d = Dialog('TurnKey Linux - First boot configuration')

        email = d.get_email(
            "TWiki Email",
            "Enter email address for the TWiki 'AdminUser' account.",
            "admin@example.com")

    inithooks_cache.write('APP_EMAIL', email)

    output = getoutput("htpasswd -bns AdminUser %s" % password)
    hashpass = output.split(":")[1].strip()

    new = []
    htpasswd = "/var/www/twiki/data/.htpasswd"
    for line in file(htpasswd).readlines():
        line = line.strip()
        if not line:
            continue

        username, password, mailaddr = line.split(":")
        if username == "AdminUser":
            password = hashpass
            mailaddr = email

        new.append(":".join([username, password, mailaddr]))

    if not new:
        new.append(':'.join(['AdminUser', hashpass, email]))

    fh = file(htpasswd, "w")
    print >> fh, "\n".join(new)
    fh.close()


if __name__ == "__main__":
    main()

