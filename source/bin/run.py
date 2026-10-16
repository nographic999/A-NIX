"""run - run a program by its file name: a .py or compiled .mpy
program (calls its run(args, cwd)), or a .sh script. A bare name in
cwd or on $PATH works without this too; `run` is for an exact path.
"""

import os
import shell


def run(args, cwd):
    if not args:
        shell._out("usage: run <file.py|file.mpy|file.sh> [args...]")
        return
    path = shell._join(cwd, args[0])
    try:
        if os.stat(path)[0] & 0x4000:
            shell._err("%s is a folder" % path)
            return cwd
    except OSError:
        shell._err("not found", path)
        return cwd
    if shell._in_lib(path):
        shell._err("%s is a library module, not a command" % path)
        return cwd
    if path.endswith(".sh"):
        return shell._run_batch(path, cwd, args[1:])
    if path.endswith(".mpy"):
        try:
            return shell._exec_mpy(path, args[1:], cwd)
        except Exception as e:
            shell._err("%s failed" % args[0], e)
            return cwd
    try:
        return shell._exec_pyfile(path, args[1:], cwd)
    except Exception as e:
        shell._err("%s failed" % args[0], e)
        return cwd
