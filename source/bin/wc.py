"""wc - count lines, words and bytes, like the real wc.

  wc <file> [file2 ...]     ... | wc

Prints: lines  words  bytes  name (plus a total for several files).
"""

import shell


def _count(f):
    lines = words = size = 0
    in_word = False
    while True:
        chunk = f.read(256)
        if not chunk:
            break
        size += len(chunk)
        for b in chunk:
            if b == 10:
                lines += 1
            if b in (32, 9, 10, 13):
                in_word = False
            elif not in_word:
                in_word = True
                words += 1
    return lines, words, size


def run(args, cwd):
    if not args:
        f = shell._input(cwd, binary=True)
        if f is None:
            shell._out("usage: wc <file> [file2 ...]")
            return
        with f:
            shell._out("%7d %7d %8d" % _count(f))
        return
    totals = [0, 0, 0]
    shown = 0
    for a in args:
        path = shell._join(cwd, a)
        try:
            with open(path, "rb") as f:
                c = _count(f)
        except OSError:
            shell._err("file not found", path)
            continue
        shell._out("%7d %7d %8d  %s" % (c + (a,)))
        for k in range(3):
            totals[k] += c[k]
        shown += 1
    if shown > 1:
        shell._out("%7d %7d %8d  total" % tuple(totals))
