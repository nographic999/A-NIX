"""mkdir - create a directory.
"""

import os
import shell


def run(args, cwd):
    if not args:
        shell._out("usage: mkdir <dir>")
        return
    for a in args:
        path = shell._join(cwd, a)
        try:
            os.mkdir(path)
        except OSError as e:
            # already exists, parent missing, filesystem full, etc. -
            # os.mkdir doesn't distinguish, so neither can we
            shell._err("could not create folder %s" % path, e)
