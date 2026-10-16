"""stat - details of a file or folder: type, size, last change.

  stat <path> [path2 ...]

The change time comes from the board's clock when the file was written;
the clock starts from a default date after every power-up unless
`date` or `date ntp` set it, so old times can look odd.
"""

import os
import time
import shell


def run(args, cwd):
    if not args:
        shell._out("usage: stat <path> [path2 ...]")
        return
    for a in args:
        path = shell._join(cwd, a)
        try:
            st = os.stat(path)
        except OSError:
            shell._err("not found", path)
            continue
        is_dir = bool(st[0] & 0x4000)
        shell._out("  path: %s" % path)
        shell._out("  type: %s" % ("folder" if is_dir else "file"))
        if is_dir:
            try:
                shell._out(" items: %d" % len(os.listdir(path)))
            except OSError:
                pass
        else:
            shell._out("  size: %d bytes" % st[6])
        mtime = st[8] if len(st) > 8 else 0
        if mtime:
            t = time.localtime(mtime)
            shell._out("change: %04d-%02d-%02d %02d:%02d:%02d" % t[:6])
