#!/usr/bin/python
"""Set MoinMoin admin password and email

Option:
    --pass=     unless provided, will ask interactively
    --email=    unless provided, will ask interactively

"""

import sys
import getopt
import inithooks_cache

from dialog_wrapper import Dialog

# ugly workaround to suppress stderr moinmoin info/warning on import
class DevNull:
    def write(self, s):
        pass

stderr = sys.stderr
sys.stderr = DevNull()

from MoinMoin.web.contexts import ScriptContext
from MoinMoin import user

sys.stderr = stderr
# -- end ugly workaround

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
            "MoinMoin Password",
            "Enter new password for the MoinMoin 'admin' account.")

    if not email:
        if 'd' not in locals():
            d = Dialog('TurnKey Linux - First boot configuration')

        email = d.get_email(
            "MoinMoin Email",
            "Enter email address for the MoinMoin 'admin' account.",
            "admin@example.com")

    inithooks_cache.write('APP_EMAIL', email)

    sys.path.append("/etc/moin")
    request = ScriptContext()
    cfg = request.cfg

    userid = user.getUserId(request, 'admin')
    u = user.User(request, userid)
    u.email = email
    u.enc_password = user.encodePassword(cfg, password)
    u.save()

if __name__ == "__main__":
    main()

