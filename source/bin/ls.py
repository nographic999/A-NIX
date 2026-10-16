"""ls - list directory contents.

  ls [-l] [path ...]

Lists a folder's entries (the current one with no argument). Files
named as arguments (typically from a glob like `ls *.py`) are listed
by name, then each folder named gets its own heading and listing,
like the real ls. `-l` is the long format (type, size, name); -a is
accepted but changes nothing - every entry is always shown.
"""

import os
import shell

def _entry(path, display_name, long_format=False):
    try:
        st = os.stat(path)
        is_dir, size = bool(st[0] & 0x4000), st[6]
    except OSError:
        shell._err("not found", path)
        return None

    name = display_name + "/" if is_dir else display_name

    if long_format:
        if is_dir:      # littlefs gives folders no real size (junk like 4294967295)
            return "d %8s  %s" % ("", shell._color_name(name))
        return "- %8d  %s" % (size, shell._color_name(name))

    return name

def _columns(names):
    if not names:
        return
    if not shell._to_screen():
        # into a file or a pipe: one name per line, like the real ls
        for name in names:
            shell._out(name)
        return

    try:
        width = shell.TERM_WIDTH
    except AttributeError:
        width = 80

    longest = max(len(name) for name in names)
    cols = max(1, width // (longest + 2))

    while cols > 1:
        rows = (len(names) + cols - 1) // cols
        widths = []

        for col in range(cols):
            start = col * rows
            end = min(start + rows, len(names))
            widths.append(max([len(x) for x in names[start:end]] or [0]))

        if sum(widths) + (2 * (cols - 1)) <= width:
            break

        cols -= 1

    rows = (len(names) + cols - 1) // cols

    widths = []

    for col in range(cols):
        start = col * rows
        end = min(start + rows, len(names))
        widths.append(max([len(x) for x in names[start:end]] or [0]))

    for row in range(rows):
        line = []

        for col in range(cols):
            i = row + col * rows

            if i >= len(names):
                break

            name = names[i]
            shown = shell._color_name(name)     # colour codes take no width

            if col < cols - 1:
                line.append(shown + " " * (widths[col] + 2 - len(name)))
            else:
                line.append(shown)

        shell._out("".join(line).rstrip())

def _list_dir(path, long_format):
    names = [n for n in (_entry(shell._join(path, name), name, long_format)
                         for name in sorted(os.listdir(path))) if n is not None]
    if long_format:
        shell._out("total %d" % len(names))
        for name in names:
            shell._out(name)
    else:
        _columns(names)


def run(args, cwd):
    long_format = False
    # -l, and -a / -la / -al (accepted: ls always shows every entry)
    while args and len(args[0]) > 1 and args[0][0] == "-" and all(c in "la" for c in args[0][1:]):
        long_format = long_format or "l" in args[0]
        args = args[1:]

    if not args:
        args = ["."]
    files, dirs = [], []
    for a in args:
        path = shell._join(cwd, a)
        try:
            st = os.stat(path)
        except OSError:
            shell._err("not found", path)
            continue
        (dirs if st[0] & 0x4000 else files).append((a, path))

    names = [n for n in (_entry(path, a, long_format) for a, path in files) if n is not None]
    if long_format:
        for name in names:
            shell._out(name)
    else:
        _columns(names)
    for k, (a, path) in enumerate(dirs):
        if len(args) > 1:               # several: a heading per folder, like real ls
            if names or k:
                shell._out()
            shell._out(a + ":")
        try:
            _list_dir(path, long_format)
        except OSError as e:
            shell._err("could not read %s" % path, e)
