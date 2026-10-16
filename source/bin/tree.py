"""tree - recursive directory listing.

Simple recursive walk with two-space indent per depth level - no
fancy box-drawing characters (the "|--" style real tree(1) uses),
just indentation, to keep this small and avoid assuming the
terminal's charset supports box-drawing glyphs.
"""

import os
import shell


def run(args, cwd):
    path = shell._join(cwd, args[0]) if args else cwd
    if not shell._is_dir(path):
        shell._err("not a folder", path)
        return

    def walk(p, prefix):
        try:
            entries = sorted(os.listdir(p))
        except OSError:
            return
        for name in entries:
            full = shell._join(p, name)
            if shell._is_dir(full):
                shell._out(prefix + shell._color_name(name + "/"))
                walk(full, prefix + "  ")
            else:
                shell._out(prefix + shell._color_name(name))

    shell._out(shell._c(shell.BLUE_BOLD, path))
    walk(path, "  ")
