"""du - how much flash space folders and files take.

  du [path]       every folder below path with its size, then the total
  du -s [path]    only the total
  du -a [path]    files too, not just folders

Sizes in KB (rounded up). Counts the bytes in files; the filesystem
itself needs a little more per file (4 KB blocks on the Pico), which
`df` includes.
"""

import os
import shell


def _walk(path, show_files, show_dirs, out):
    total = 0
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return 0
    for name in names:
        full = shell._join(path, name)
        try:
            st = os.stat(full)
        except OSError:
            continue
        if st[0] & 0x4000:
            total += _walk(full, show_files, show_dirs, out)
        else:
            total += st[6]
            if show_files:
                out(st[6], full)
    if show_dirs:
        out(total, path)
    return total


def run(args, cwd):
    summary = "-s" in args
    files = "-a" in args
    rest = [a for a in args if a not in ("-s", "-a")]
    path = shell._join(cwd, rest[0]) if rest else cwd

    def out(size, name):
        shell._out("%7d KB  %s" % ((size + 1023) // 1024, name))

    try:
        st = os.stat(path)
    except OSError:
        shell._err("not found", path)
        return
    if not st[0] & 0x4000:
        out(st[6], path)
        return
    total = _walk(path, files and not summary, not summary, out)
    if summary:
        out(total, path)
