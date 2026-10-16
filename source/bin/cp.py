"""cp - copy file(s), or directories with -r.

Copying itself (one file, or a whole folder with -r) is in
/lib/fileops.py, shared with `rm -r`.
"""

import os
import fileops
import shell


def run(args, cwd):
    recursive = False
    if args and args[0] in ("-r", "-R"):
        recursive, args = True, args[1:]
    if len(args) < 2:
        shell._out("usage: cp [-r] <src> [src2 ...] <dst>")
        return
    sources, dst_arg = args[:-1], args[-1]
    dst_path = shell._join(cwd, dst_arg)
    dst_is_dir = shell._is_dir(dst_path)
    if dst_arg.endswith("/") and not dst_is_dir:
        shell._err("no such folder: %s" % dst_path)
        return
    if len(sources) > 1 and not dst_is_dir:
        shell._err("destination must be a directory when copying multiple files")
        return
    count = 0
    for src_arg in sources:
        src_path = shell._join(cwd, src_arg)
        try:
            src_is_dir = shell._is_dir(src_path)
            os.stat(src_path)  # just to raise OSError if src doesn't exist at all
        except OSError:
            shell._err("source not found", src_path)
            continue
        target = shell._join(dst_path, shell._basename(src_arg)) if dst_is_dir else dst_path
        if target == src_path:
            shell._err("%s and %s are the same file" % (src_path, target))
            continue
        if src_is_dir:
            if not recursive:
                shell._err("%s is a folder (use -r to copy folders)" % src_path)
                continue
            if fileops.copy_tree(src_path, target):
                count += 1
        elif fileops.copy_file(src_path, target):
            count += 1
    shell._out("%d item(s) copied" % count)
