"""touch - create an empty file if it doesn't exist.

  touch <file> [file2 ...]

An existing file is left unchanged (the Pico's filesystem has no
way to just update a file's time).
"""

import os
import shell


def run(args, cwd):
    if not args:
        shell._out("usage: touch <file> [file2 ...]")
        return
    for a in args:
        path = shell._join(cwd, a)
        try:
            os.stat(path)
            continue
        except OSError:
            pass
        try:
            open(path, "w").close()
        except OSError as e:
            shell._err("could not create %s" % path, e)
