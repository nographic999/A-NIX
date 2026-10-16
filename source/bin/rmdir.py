"""rmdir - remove an empty directory.

Deliberately does NOT recurse or force-remove a non-empty
directory - that's what `rm -r` is for. os.rmdir() itself refuses
a non-empty directory, so this is just a thin wrapper around that.
"""

import os
import shell


def run(args, cwd):
    if not args:
        shell._out("usage: rmdir <dir>")
        return
    for a in args:
        path = shell._join(cwd, a)
        try:
            os.rmdir(path)
        except OSError as e:
            code = e.args[0] if e.args else None
            if code == 2:
                shell._err("not found", path)
            elif code in (39, 66, 90):          # ENOTEMPTY (by platform)
                shell._err("%s is not empty - rm -r removes it with everything in it" % path)
            elif code == 20:
                shell._err("%s is a file - use rm" % path)
            else:
                shell._err("could not remove directory %s" % path, e)
