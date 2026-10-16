"""uniq - drop repeated lines that follow each other (like the real
uniq; `sort | uniq` removes all repeats).

  uniq [-c] [file]        ... | uniq [-c]

  -c  show how many times each line was repeated
"""

import shell


def run(args, cwd):
    count = "-c" in args
    files = [a for a in args if a != "-c"]
    try:
        f = shell._input(cwd, files[0] if files else None)
    except OSError:
        shell._err("file not found", shell._join(cwd, files[0]))
        return
    if f is None:
        shell._out("usage: uniq [-c] <file>")
        return
    prev = None
    n = 0

    def emit():
        if prev is not None:
            shell._out(("%7d %s" % (n, prev)) if count else prev)

    with f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if line == prev:
                n += 1
                continue
            emit()
            prev = line
            n = 1
    emit()
