"""df - show total/used/free flash space for a filesystem path, in
kilobytes (1 KB = 1024 bytes) by default, or in bytes with -b.

os.statvfs() returns a tuple whose fields match the real POSIX
statvfs struct; the ones used here are index 0 (block size in
bytes) and indexes 2/3 (total/free blocks) - multiplying block
size by block count gives bytes.
"""

import os
import shell


def run(args, cwd):
    in_bytes = "-b" in args
    args = [a for a in args if a != "-b"]
    path = shell._join(cwd, args[0]) if args else "/"
    try:
        st = os.statvfs(path)
    except OSError as e:
        shell._err("could not check disk", e)
        return
    bsize, blocks, bfree = st[0], st[2], st[3]
    total = bsize * blocks
    free = bsize * bfree
    used = total - free
    if in_bytes:
        unit, div = "bytes", 1
    else:
        unit, div = "KB", 1024
    shell._out("filesystem: %s" % path)
    shell._out("%10d %s total" % (total // div, unit))
    shell._out("%10d %s used" % (used // div, unit))
    shell._out("%10d %s free" % (free // div, unit))
