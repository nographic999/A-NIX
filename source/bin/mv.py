"""mv - move/rename file(s).

os.rename() does the actual move - MicroPython's filesystem
supports it directly (no separate copy+delete needed, unlike `cp`
which genuinely has to copy byte-for-byte since source and
destination are different files by definition).
"""

import os
import shell


def run(args, cwd):
    if len(args) < 2:
        shell._out("usage: mv <src> [src2 ...] <dst>")
        return
    sources, dst_arg = args[:-1], args[-1]
    dst_path = shell._join(cwd, dst_arg)
    dst_is_dir = shell._is_dir(dst_path)
    # moving several files at once only makes sense into a directory -
    # there's no single "combine into one destination file" meaning
    if len(sources) > 1 and not dst_is_dir:
        shell._err("destination must be a directory when moving multiple files")
        return
    count = 0
    for src_arg in sources:
        src_path = shell._join(cwd, src_arg)
        target = shell._join(dst_path, shell._basename(src_arg)) if dst_is_dir else dst_path
        if (target.rstrip("/") + "/").startswith(src_path.rstrip("/") + "/"):
            shell._err("cannot move %s into itself" % src_path)
            continue
        try:
            os.rename(src_path, target)
            count += 1
        except OSError as e:
            shell._err("could not move %s" % src_path, e)
    shell._out("%d item(s) moved" % count)
