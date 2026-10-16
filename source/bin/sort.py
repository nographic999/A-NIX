"""sort - sort lines.

  sort [-r] [-n] [-u] [file]        ... | sort

  -r  reverse      -n  by number (lines starting with a number)
  -u  drop repeated lines

All lines are held in RAM, so very big files (more than about a
third of `free`) may not fit.
"""

import shell


def _numkey(line):
    word = line.strip().split(None, 1)
    try:
        return (0, float(word[0]) if word else 0.0, line)
    except ValueError:
        return (1, 0.0, line)


def run(args, cwd):
    opts = ""
    files = []
    for a in args:
        if len(a) > 1 and a[0] == "-" and all(c in "rnu" for c in a[1:]):
            opts += a[1:]
        else:
            files.append(a)
    try:
        f = shell._input(cwd, files[0] if files else None)
    except OSError:
        shell._err("file not found", shell._join(cwd, files[0]))
        return
    if f is None:
        shell._out("usage: sort [-r] [-n] [-u] <file>")
        return
    with f:
        lines = [ln.rstrip("\n").rstrip("\r") for ln in f]
    if "n" in opts:
        lines.sort(key=_numkey, reverse="r" in opts)
    else:
        lines.sort(reverse="r" in opts)
    prev = None
    for ln in lines:
        if "u" in opts and ln == prev:
            continue
        shell._out(ln)
        prev = ln
