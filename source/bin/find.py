"""find - search for files and directories by name.

  find [path] [pattern]

Walks path (default: current directory) and everything below it,
printing every entry whose name matches pattern (* and ? like the
shell's globs - quote it so the shell doesn't expand it first:
find / "*.py"). No pattern lists everything. Directories end in /.
"""

import os
import shell


def run(args, cwd):
    if len(args) > 2:
        shell._out('usage: find [path] ["pattern"]')
        return
    start, shown = cwd, "."
    pattern = None
    if len(args) == 2:
        start, shown, pattern = shell._join(cwd, args[0]), args[0], args[1]
    elif len(args) == 1:
        if shell._is_dir(shell._join(cwd, args[0])):
            start, shown = shell._join(cwd, args[0]), args[0]
        else:
            pattern = args[0]
    shown = shown.rstrip("/") if shown != "/" else ""
    if not shell._is_dir(start):
        shell._err("not a folder", start)
        return

    found = [0]

    def walk(path):
        try:
            names = sorted(os.listdir(path))
        except OSError:
            return
        for name in names:
            full = shell._join(path, name)
            is_dir = shell._is_dir(full)
            if pattern is None or shell._glob_match(pattern, name):
                shell._out(shown + full[len(start.rstrip("/")):] + ("/" if is_dir else ""))
                found[0] += 1
            if is_dir:
                walk(full)

    walk(start)
    if found[0] == 0:
        shell._set_status(1)
