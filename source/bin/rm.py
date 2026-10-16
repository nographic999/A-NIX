"""rm - remove file(s), or directories with -r.

Refuses to touch a directory without -r (matches real rm's
behavior) rather than silently doing nothing or erroring
unhelpfully - the message tells you exactly what flag you need.
"""

import os
import fileops
import shell


def run(args, cwd):
    recursive = False
    if args and args[0] in ("-r", "-R"):
        recursive, args = True, args[1:]
    if not args:
        shell._out("usage: rm [-r] <file> [file2 ...]")
        return
    count = 0
    for a in args:
        path = shell._join(cwd, a)
        if shell._is_dir(path):
            if (cwd.rstrip("/") + "/").startswith(path.rstrip("/") + "/"):
                shell._err("%s holds the current folder - cd out of it first" % path)
                continue
            if not recursive:
                shell._err("%s is a folder (use -r to remove folders)" % path)
                continue
            if fileops.remove_tree(path):
                count += 1
        else:
            try:
                os.remove(path)
                count += 1
            except OSError as e:
                shell._err("could not remove %s" % path, e)
    shell._out("%d item(s) removed" % count)
